"""JSON-backed API-key management for Synthra."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_KEY_PREFIX = "synthra_live_"
_STORE_LOCK = threading.RLock()


def api_keys_path() -> Path:
    """Return the configured JSON key store or its private home-directory default."""
    configured_path = os.environ.get("SYNTHRA_API_KEYS_FILE")
    if configured_path:
        return Path(configured_path).expanduser()
    return Path.home() / ".synthra" / "api_keys.json"


def hash_api_key(api_key: str) -> str:
    """Return the SHA-256 digest of a raw API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _read_keys() -> list[dict[str, Any]]:
    path = api_keys_path()
    try:
        with path.open(encoding="utf-8") as key_file:
            data = json.load(key_file)
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read API-key storage: {error}") from error

    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise RuntimeError("API-key storage must contain a JSON list of key records.")
    return data


def _write_keys(keys: list[dict[str, Any]]) -> None:
    path = api_keys_path()
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with temporary_path.open("x", encoding="utf-8") as key_file:
            os.chmod(temporary_path, 0o600)
            json.dump(keys, key_file, indent=2)
            key_file.write("\n")
            key_file.flush()
            os.fsync(key_file.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except OSError as error:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"Could not write API-key storage: {error}") from error


def create_api_key(name: str, scopes: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    """Create a random key, persisting its digest and non-secret metadata only."""
    api_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    record: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "name": name,
        "key_hash": hash_api_key(api_key),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scopes": list(scopes) if scopes is not None else ["chat"],
        "active": True,
        "request_count": 0,
    }
    with _STORE_LOCK:
        keys = _read_keys()
        keys.append(record)
        _write_keys(keys)
    return api_key, record


def list_api_keys() -> list[dict[str, Any]]:
    """Return key records for administrative use; callers must redact hashes."""
    with _STORE_LOCK:
        return _read_keys()


def public_key_metadata(record: dict[str, Any]) -> dict[str, Any]:
    """Return the explicitly non-secret metadata fields for an API key."""
    return {
        "id": record["id"],
        "name": record["name"],
        "created_at": record["created_at"],
        "scopes": record["scopes"],
        "active": record["active"],
        "request_count": record["request_count"],
    }


def find_api_key(api_key: str) -> dict[str, Any] | None:
    """Find a key using constant-time digest comparisons."""
    candidate_hash = hash_api_key(api_key)
    with _STORE_LOCK:
        for record in _read_keys():
            saved_hash = record.get("key_hash")
            if isinstance(saved_hash, str) and hmac.compare_digest(
                saved_hash, candidate_hash
            ):
                return record
    return None


def revoke_api_key(key_id: str) -> bool:
    """Mark a matching key inactive, returning whether it was found."""
    with _STORE_LOCK:
        keys = _read_keys()
        for record in keys:
            if record.get("id") == key_id:
                record["active"] = False
                _write_keys(keys)
                return True
    return False


def increment_request_count(key_id: str) -> None:
    """Persist one successful authenticated chat request for the key."""
    with _STORE_LOCK:
        keys = _read_keys()
        for record in keys:
            if record.get("id") == key_id and record.get("active") is True:
                record["request_count"] = int(record.get("request_count", 0)) + 1
                _write_keys(keys)
                return
        raise RuntimeError("API key was revoked before its request was recorded.")
