#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.synthra_admin_token"

if [[ "$#" -ne 1 || -z "$1" ]]; then
    printf 'Usage: %s "App name"\n' "$0" >&2
    exit 2
fi

if [[ -z "${ADMIN_TOKEN:-}" ]]; then
    if [[ ! -r "$TOKEN_FILE" ]]; then
        printf 'Admin token not found. Run ./setup_api_key.sh first.\n' >&2
        exit 1
    fi
    IFS= read -r ADMIN_TOKEN < "$TOKEN_FILE" || true
fi

if [[ -z "${ADMIN_TOKEN:-}" ]]; then
    printf 'Admin token is empty. Run ./setup_api_key.sh again.\n' >&2
    exit 1
fi

export ADMIN_TOKEN
export SYNTHRA_API_URL="${SYNTHRA_API_URL:-http://127.0.0.1:8000}"

python3 - "$1" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

url = os.environ["SYNTHRA_API_URL"].rstrip("/") + "/admin/keys"
payload = json.dumps({"name": sys.argv[1], "scopes": ["chat"]}).encode()
request = urllib.request.Request(
    url,
    data=payload,
    headers={
        "Authorization": "Bearer " + os.environ["ADMIN_TOKEN"],
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
except urllib.error.HTTPError as error:
    detail = error.read().decode("utf-8", errors="replace")
    print(f"API-key creation failed (HTTP {error.code}): {detail}", file=sys.stderr)
    raise SystemExit(1)
except (urllib.error.URLError, TimeoutError) as error:
    print(f"Could not reach Synthra at {url}: {error}", file=sys.stderr)
    raise SystemExit(1)
except (json.JSONDecodeError, KeyError) as error:
    print(f"Synthra returned an invalid API-key response: {error}", file=sys.stderr)
    raise SystemExit(1)

api_key = result.get("api_key")
key_id = result.get("key_id")
if not isinstance(api_key, str) or not isinstance(key_id, str):
    print("Synthra returned an invalid API-key response.", file=sys.stderr)
    raise SystemExit(1)

print("Copy and save this API key now; it will not be shown again:")
print(api_key)
print(f"Key ID (for revocation): {key_id}")
PY
