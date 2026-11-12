from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from rate_limit import RateLimiter


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("SYNTHRA_API_KEYS_FILE", str(tmp_path / "api_keys.json"))
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(server, "rate_limiter", RateLimiter(limit=30))
    monkeypatch.setattr(server, "_call_local_model", lambda _message: ("test", "ok"))
    with TestClient(server.app) as test_client:
        yield test_client


def create_key(client: TestClient, name: str) -> str:
    response = client.post(
        "/admin/keys",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"name": name},
    )
    assert response.status_code == 201
    return response.json()["api_key"]


def chat(client: TestClient, key: str) -> TestClient:
    return client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {key}"},
        json={"message": "hello"},
    )


def test_first_30_requests_succeed_and_request_31_is_limited(
    client: TestClient,
) -> None:
    key = create_key(client, "Rate limited app")

    responses = [chat(client, key) for _ in range(30)]
    limited = chat(client, key)

    assert all(response.status_code == 200 for response in responses)
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Too many requests. Try again later."


def test_different_api_keys_have_separate_rate_limits(client: TestClient) -> None:
    first_key = create_key(client, "First app")
    second_key = create_key(client, "Second app")

    assert all(chat(client, first_key).status_code == 200 for _ in range(30))
    assert chat(client, first_key).status_code == 429
    assert chat(client, second_key).status_code == 200


def test_limiter_resets_after_one_minute() -> None:
    limiter = RateLimiter(limit=30, window_seconds=60)

    assert all(limiter.allow("key-id", now=10) for _ in range(30))
    assert not limiter.allow("key-id", now=11)
    assert limiter.allow("key-id", now=70)
