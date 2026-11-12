#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.synthra_admin_token"

if [[ -z "${ADMIN_TOKEN:-}" ]]; then
    ADMIN_TOKEN="$(python3 -c 'import secrets; print("synthra_admin_" + secrets.token_urlsafe(32))')"
    printf 'Synthra admin token created.\n'
    printf 'ADMIN_TOKEN: %s\n' "$ADMIN_TOKEN"
else
    printf 'Using ADMIN_TOKEN already set in the environment.\n'
fi

umask 077
temporary_file="$(mktemp "$SCRIPT_DIR/.synthra_admin_token.XXXXXX")"
trap 'rm -f -- "$temporary_file"' EXIT
printf '%s\n' "$ADMIN_TOKEN" > "$temporary_file"
chmod 600 "$temporary_file"
mv -f -- "$temporary_file" "$TOKEN_FILE"
trap - EXIT

export ADMIN_TOKEN
cd "$SCRIPT_DIR"

cat <<'INSTRUCTIONS'

Starting Synthra API server...
Server: http://127.0.0.1:8000

To create an app API key, open a new terminal and run:
  ./create_api_key.sh "My iPad App"

Copy and save the printed synthra_live_... key securely; it is shown only once.
Test /v1/chat with:
  curl -X POST http://127.0.0.1:8000/v1/chat \
    -H "Authorization: Bearer synthra_live_YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{"message":"Hello Synthra"}'

To revoke a key, list keys with:
  export ADMIN_TOKEN="$(<.synthra_admin_token)"
  curl http://127.0.0.1:8000/admin/keys \
    -H "Authorization: Bearer $ADMIN_TOKEN"
Then delete it using its key ID:
  curl -X DELETE http://127.0.0.1:8000/admin/keys/KEY_ID \
    -H "Authorization: Bearer $ADMIN_TOKEN"

Stop the server with Ctrl-C.
INSTRUCTIONS

exec python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 --no-access-log
