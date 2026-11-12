# Application APIs

## Local chat API

- `GET /health` reports whether the local API server is running.
- `POST /v1/chat` accepts a JSON `message` and requires a bearer API key with
  the `chat` scope.
- `POST /admin/keys`, `GET /admin/keys`, and
  `DELETE /admin/keys/{key_id}` manage local API keys and require the admin
  bearer token.

API chat uses the local Ollama service and does not have coding-agent tools.
