"""HTTP API for local Synthra chat and API-key administration."""

from __future__ import annotations

import hmac
import os
import re
import time
import uuid
from typing import Annotated, Any

import ollama
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

import api_keys
from rate_limit import RateLimiter

DEFAULT_MODEL = "qwen2.5-coder:7b"
FALLBACK_MODEL = "llama3.2:3b"
API_RATE_LIMIT = 30

_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_SYNTHRA_KEY = re.compile(r"\bsynthra_live_[A-Za-z0-9_-]+\b")
_SECRET_ASSIGNMENT = re.compile(
    r"""(?im)(\b[\w.-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"""
    r"""auth[_-]?token|client[_-]?secret|secret|password|passwd|token)[\w.-]*"""
    r"""\s*[:=]\s*)"""
    r"""(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)"""
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_COMMON_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"
)

app = FastAPI(title="Synthra API", version="0.5.0")
rate_limiter = RateLimiter(limit=API_RATE_LIMIT, window_seconds=60.0)


class CreateAPIKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["chat"], max_length=20)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class APIKeyMetadata(BaseModel):
    id: str
    name: str
    created_at: str
    scopes: list[str]
    active: bool
    request_count: int


class ChatResponse(BaseModel):
    reply: str
    model: str
    request_id: str


def redact_secrets(text: str) -> str:
    """Redact common credential formats before sending user text to the model."""
    redacted = _PRIVATE_KEY_BLOCK.sub("[REDACTED PRIVATE KEY]", text)
    redacted = _BEARER_SECRET.sub("Bearer [REDACTED]", redacted)
    redacted = _SYNTHRA_KEY.sub("[REDACTED API KEY]", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", redacted)
    return _COMMON_TOKEN.sub("[REDACTED TOKEN]", redacted)


def _require_admin_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected_token = os.environ.get("ADMIN_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_TOKEN is not configured in the environment.",
        )
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, separator, supplied_token = authorization.partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied_token, expected_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _require_api_key(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, separator, supplied_key = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not supplied_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        record = api_keys.find_api_key(supplied_key)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API-key storage is unavailable.",
        ) from error
    if record is None or record.get("active") is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return record


def _available_model_names(client: Any) -> set[str]:
    response = client.list()
    models = response.get("models", []) if isinstance(response, dict) else response.models
    names: set[str] = set()
    for model in models:
        name = model.get("name") if isinstance(model, dict) else getattr(model, "name", None)
        if isinstance(name, str):
            names.add(name)
    return names


def _chat_local_response(client: Any, model: str, prompt: str) -> Any:
    """Retry one transient Ollama runner failure after its process restarts."""
    for attempt in range(2):
        try:
            return client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={"num_ctx": 3072, "num_thread": 2},
            )
        except ollama.ResponseError as error:
            if attempt or error.status_code < 500:
                raise
            time.sleep(0.5)
    raise RuntimeError("Local model request ended without a response.")


def _call_local_model(message: str) -> tuple[str, str]:
    """Chat with local Ollama without passing any coding-agent tools."""
    model = os.environ.get("SYNTHRA_MODEL", DEFAULT_MODEL)
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    client = ollama.Client(host=host)
    prompt = (
        "You are Synthra, a helpful local multi-language coding assistant. "
        "This API has chat-only access: you cannot inspect or change files "
        "and cannot run commands. Do not claim to have used tools.\n\n"
        f"User request:\n{redact_secrets(message)}"
    )
    try:
        response: Any = _chat_local_response(client, model, prompt)
    except (ollama.RequestError, ollama.ResponseError) as original_error:
        if model != DEFAULT_MODEL:
            raise
        try:
            fallback_available = FALLBACK_MODEL in _available_model_names(client)
        except (ollama.RequestError, ollama.ResponseError, AttributeError):
            fallback_available = False
        if not fallback_available:
            raise original_error
        model = FALLBACK_MODEL
        response = _chat_local_response(client, model, prompt)

    response_message = (
        response.get("message", {})
        if isinstance(response, dict)
        else getattr(response, "message", None)
    )
    reply = (
        response_message.get("content", "")
        if isinstance(response_message, dict)
        else getattr(response_message, "content", "")
    )
    return model, str(reply or "")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "Synthra v0.5"}


@app.post(
    "/admin/keys",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_admin_token)],
)
def create_key(request: CreateAPIKeyRequest, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    try:
        raw_key, record = api_keys.create_api_key(request.name, request.scopes)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return {
        "message": "Save this key now. You will not see it again.",
        "api_key": raw_key,
        "key_id": record["id"],
        "scopes": record["scopes"],
    }


@app.get(
    "/admin/keys",
    response_model=list[APIKeyMetadata],
    dependencies=[Depends(_require_admin_token)],
)
def get_keys() -> list[dict[str, Any]]:
    try:
        records = api_keys.list_api_keys()
        return [api_keys.public_key_metadata(record) for record in records]
    except (RuntimeError, KeyError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API-key storage is unavailable or invalid.",
        ) from error


@app.delete(
    "/admin/keys/{key_id}",
    dependencies=[Depends(_require_admin_token)],
)
def delete_key(key_id: str) -> dict[str, str]:
    try:
        revoked = api_keys.revoke_api_key(key_id)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API-key storage is unavailable.",
        ) from error
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    return {"message": "API key revoked."}


@app.post("/v1/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    response: Response,
    key_record: Annotated[dict[str, Any], Depends(_require_api_key)],
) -> ChatResponse:
    response.headers["Cache-Control"] = "no-store"
    if "chat" not in key_record.get("scopes", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API key does not have the chat scope.",
        )
    key_id = key_record["id"]
    if not rate_limiter.allow(key_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": "60"},
        )
    try:
        api_keys.increment_request_count(key_id)
        model, reply = _call_local_model(request.message)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API-key storage is unavailable.",
        ) from error
    except (ollama.RequestError, ollama.ResponseError, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not get a response from the local Ollama service.",
        ) from error
    return ChatResponse(reply=reply, model=model, request_id=uuid.uuid4().hex)
