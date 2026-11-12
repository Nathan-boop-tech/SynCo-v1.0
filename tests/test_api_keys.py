import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api_keys
import server
from rate_limit import RateLimiter

ADMIN_HEADERS = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("SYNTHRA_API_KEYS_FILE", str(tmp_path / "api_keys.json"))
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(server, "rate_limiter", RateLimiter(limit=30))
    with TestClient(server.app) as test_client:
        yield test_client


def create_key(
    client: TestClient, scopes: list[str] | None = None
) -> dict[str, Any]:
    response = client.post(
        "/admin/keys",
        headers=ADMIN_HEADERS,
        json={"name": "Test App", **({"scopes": scopes} if scopes is not None else {})},
    )
    assert response.status_code == 201
    return response.json()


def test_admin_can_create_key_and_only_hash_is_stored(
    client: TestClient, tmp_path: Path
) -> None:
    result = create_key(client)
    key = result["api_key"]

    assert result["message"] == "Save this key now. You will not see it again."
    assert key.startswith("synthra_live_")
    assert result["scopes"] == ["chat"]

    store_path = tmp_path / "api_keys.json"
    stored_text = store_path.read_text(encoding="utf-8")
    stored_records = json.loads(stored_text)
    assert key not in stored_text
    assert len(stored_records) == 1
    record = stored_records[0]
    assert record["key_hash"] == hashlib.sha256(key.encode()).hexdigest()
    assert record["name"] == "Test App"
    assert record["scopes"] == ["chat"]
    assert record["active"] is True
    assert record["request_count"] == 0
    assert set(record) == {
        "id",
        "name",
        "key_hash",
        "created_at",
        "scopes",
        "active",
        "request_count",
    }


def test_missing_admin_token_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN")

    response = client.post("/admin/keys", json={"name": "No Admin"})

    assert response.status_code == 503
    assert "ADMIN_TOKEN" in response.json()["detail"]


def test_wrong_admin_token_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/admin/keys",
        headers={"Authorization": "Bearer wrong-token"},
        json={"name": "No Admin"},
    )

    assert response.status_code == 401


def test_created_key_can_chat_and_increments_metadata_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_key(client)
    received_messages: list[str] = []

    def fake_chat(message: str) -> tuple[str, str]:
        received_messages.append(message)
        return "test-local-model", "Here is an explanation."

    monkeypatch.setattr(server, "_call_local_model", fake_chat)
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {result['api_key']}"},
        json={"message": "Explain a function"},
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "Here is an explanation."
    assert response.json()["model"] == "test-local-model"
    assert response.json()["request_id"]
    assert received_messages == ["Explain a function"]
    listed = client.get("/admin/keys", headers=ADMIN_HEADERS).json()
    assert listed[0]["request_count"] == 1


def test_missing_and_invalid_keys_are_rejected(client: TestClient) -> None:
    missing = client.post("/v1/chat", json={"message": "Hello"})
    invalid = client.post(
        "/v1/chat",
        headers={"Authorization": "Bearer synthra_live_not-a-real-key"},
        json={"message": "Hello"},
    )
    malformed = client.post(
        "/v1/chat",
        headers={"Authorization": "Basic not-a-key"},
        json={"message": "Hello"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert malformed.status_code == 401


def test_revoked_key_is_rejected(client: TestClient) -> None:
    result = create_key(client)

    revoked = client.delete(
        f"/admin/keys/{result['key_id']}", headers=ADMIN_HEADERS
    )
    rejected = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {result['api_key']}"},
        json={"message": "Hello"},
    )

    assert revoked.status_code == 200
    assert revoked.json()["message"]
    assert rejected.status_code == 401


def test_key_without_chat_scope_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_key(client, scopes=["admin"])
    monkeypatch.setattr(
        server,
        "_call_local_model",
        lambda _message: pytest.fail("Wrong-scope key reached the model"),
    )

    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {result['api_key']}"},
        json={"message": "Hello"},
    )

    assert response.status_code == 403


def test_admin_key_list_never_returns_hash_or_raw_key(client: TestClient) -> None:
    result = create_key(client)

    response = client.get("/admin/keys", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    metadata = response.json()[0]
    assert metadata == {
        "id": result["key_id"],
        "name": "Test App",
        "created_at": metadata["created_at"],
        "scopes": ["chat"],
        "active": True,
        "request_count": 0,
    }
    assert "key_hash" not in response.text
    assert result["api_key"] not in response.text


def test_secret_like_text_is_redacted_before_local_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_key(client)
    captured: dict[str, Any] = {}

    class FakeOllamaClient:
        def __init__(self, *, host: str) -> None:
            captured["host"] = host

        def chat(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(server.ollama, "Client", FakeOllamaClient)
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {result['api_key']}"},
        json={
            "message": (
                "Please check api_key=example_secret_123 and "
                "SERVICE_API_KEY=another_secret_456 and "
                f"Bearer {result['api_key']}"
            )
        },
    )

    assert response.status_code == 200
    sent_text = captured["messages"][0]["content"]
    assert "Synthra" in sent_text
    assert "example_secret_123" not in sent_text
    assert "another_secret_456" not in sent_text
    assert result["api_key"] not in sent_text
    assert "[REDACTED]" in sent_text


def test_local_model_helper_retries_one_transient_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeOllamaClient:
        def __init__(self, *, host: str) -> None:
            pass

        def chat(self, **_kwargs: Any) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise server.ollama.ResponseError("runner restarted", 500)
            return {"message": {"content": "ok"}}

    monkeypatch.setenv("SYNTHRA_MODEL", "llama3.2:3b")
    monkeypatch.setattr(server.ollama, "Client", FakeOllamaClient)

    assert server._call_local_model("hello") == ("llama3.2:3b", "ok")
    assert calls == 2


def test_health_does_not_require_a_key(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Synthra v0.5"}


def test_legacy_api_module_exposes_the_new_server_app() -> None:
    import api

    assert api.app is server.app
