# Synthra v0.3

Synthra is a local, terminal-based multi-language coding agent. It uses
[Ollama](https://ollama.com/) for local model inference and approval-gated tools
to inspect a project, read files, make focused edits, run supported commands,
and report results. Version 0.3 adds an optional FastAPI chat API protected by
API keys. It does not use a hosted AI provider.

## Supported languages

Synthra detects languages from file extensions and provides conventional
commands, package-manager guidance, and notes for missing tools.

| Language | Extensions | Run / test guidance | Package manager or build tool |
| --- | --- | --- | --- |
| Python | `.py` | `python file.py`; `python -m pytest` | pip |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | `node file.js`; `npm test` | npm |
| TypeScript | `.ts`, `.tsx` | `npx --no-install tsx file.ts` or `tsc`; `npm test` | npm |
| HTML | `.html`, `.htm` | Browser preview; no standard test | None |
| CSS | `.css` | Preview an HTML page in a browser; no standard test | None |
| Java | `.java` | `javac` and `java`; Maven or Gradle tests | Maven or Gradle |
| C | `.c` | `gcc`; `make test` or CTest when configured | Make or CMake |
| C++ | `.cc`, `.cpp`, `.cxx`, `.hpp`, `.hh`, `.hxx` | `g++`; `make test` or CTest when configured | CMake or Make |
| C# | `.cs` | `dotnet run`; `dotnet test` | dotnet |
| Go | `.go` | `go run`; `go test ./...` | Go modules |
| Rust | `.rs` | `cargo run`; `cargo test` | Cargo |
| Swift | `.swift` | `swift run`; `swift test` | Swift Package Manager |
| SQL | `.sql` | Database-specific client; tests depend on the project | Database-specific |
| Bash / Shell | `.sh`, `.bash` | `bash file.sh`; `shellcheck` or `bash -n` | OS package manager if needed |

Commands are suggestions, not assumptions: Synthra checks for available
executables and project configuration before running tests. When a compiler,
runtime, test runner, or project test setup is missing, it explains what is
needed rather than installing it.

If a project contains multiple languages and a request does not make the target
clear, Synthra asks which language to work on.

## Requirements and dependencies

- Python 3.11 or newer
- Ollama installed and running on this machine
- A model pulled into Ollama

Install the Python dependencies:

```bash
pip install -r requirements.txt
```

## API Keys

The optional FastAPI server lets approved apps chat with Synthra through the
local Ollama model. API clients get chat-only access: they cannot use the
coding agent's file-writing or command-running tools.

Install dependencies and start local Ollama as described above. From the
repository directory, start the API and generate a local admin token:

```bash
./setup_api_key.sh
```

The script saves the admin token in `.synthra_admin_token` with owner-only
permissions and starts the server at `http://127.0.0.1:8000`. The token file is
ignored by Git. Keep it private; do not put real admin or app keys in source
code, Git, or `.env`. If `ADMIN_TOKEN` is already set, the script uses and
saves that value instead of generating a new one. If the default Qwen model
cannot start and `llama3.2:3b` is installed, the server retries with that local
fallback.

Create a separate key for each app from a second terminal:

```bash
./create_api_key.sh "My iPad App"
```

Copy and save the printed `synthra_live_...` key securely; it is shown only
once. The JSON key store contains only its SHA-256 hash and metadata. The
default store is `~/.synthra/api_keys.json`; set `SYNTHRA_API_KEYS_FILE` to
choose a different path. The file and its parent directory are created with
owner-only permissions.

Call the chat endpoint with the app key:

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Authorization: Bearer synthra_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Create a Python function that adds two numbers."}'
```

The response includes `reply`, `model`, and a unique `request_id`. Requests are
sent only to the local Ollama service, with common credential patterns
redacted from the prompt before model inference. Do not send secrets: no
pattern-based redaction can identify every possible secret format.

List key metadata or revoke a key with the admin token:

```bash
export ADMIN_TOKEN="$(<.synthra_admin_token)"

curl http://localhost:8000/admin/keys \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X DELETE http://localhost:8000/admin/keys/KEY_ID \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The list endpoint returns key ID, name, creation time, scopes, active status,
and request count, but never returns hashes or raw keys. Revoked keys are
rejected. Only keys with the `chat` scope can call `/v1/chat`.

Each key ID can make 30 requests per minute. Request 31 receives HTTP 429 with
`Too many requests. Try again later.` The in-memory limiter resets after one
minute and when the server restarts; it is intended for a single server
process, not a multi-worker deployment. The JSON key store coordinates writes
within that process only, so run one worker to avoid cross-process update races.

`/health` is public and does not need a key. The setup script configures
`ADMIN_TOKEN` for the server automatically. The server binds to loopback so
local apps can connect. For remote apps, put the service behind HTTPS and
appropriate network controls rather than exposing the development server
directly.

To add another app later, repeat `POST /admin/keys` with a distinct name,
securely deliver the one-time key to that app, and revoke it independently if
the app no longer needs access.

## Install and run Ollama

Install Ollama using the official installer for your platform. On Linux:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start the local Ollama service in a separate terminal:

```bash
ollama serve
```

Pull the default model:

```bash
ollama pull qwen2.5-coder:7b
```

If `qwen2.5-coder:7b` is not installed or cannot start, Synthra uses
`llama3.2:3b` when that fallback model is already installed. Pull it with:

```bash
ollama pull llama3.2:3b
```

## Configure and run Synthra

Set the model and (optionally) the local Ollama service address:

```bash
export SYNTHRA_MODEL="qwen2.5-coder:7b"
export OLLAMA_HOST="http://localhost:11434"
python agent.py
```

`.env.example` documents these values. Synthra does not automatically load a
`.env` file; export the variables in your shell or configure them through your
local environment. Type `/exit` to end the chat.

Example requests:

- `Inspect this project and tell me what languages it uses.`
- `Explain what the Go files in this project do.`
- `Fix the failing Python test.` Synthra inspects the project and asks before
  writing files or running commands.

## Language detection and tools

`languages.py` maps supported file extensions to language rules: normal run and
test commands, the usual package manager or build tool, and notes about
requirements. Synthra uses those rules to choose project-relevant commands and
to explain missing tools. HTML and CSS are preview-oriented and do not have a
standard test command; SQL execution and testing depend on the selected
database.

## Approval and safety

- File tools stay inside the current project and reject absolute paths and
  `../` traversal.
- Synthra will not read or write paths identified as `.git`, `.env`, secrets, or
  credentials.
- Synthra shows a preview and asks `Allow Synthra to write this file? (yes/no)`
  before each file write.
- Synthra asks `Allow Synthra to run this command? (yes/no)` before each
  allowlisted command. Commands run without a shell and have a 60-second
  timeout.
- Dangerous command patterns and commands unrelated to detected project
  languages are blocked. Synthra does not delete files.
- Missing tools are reported with installation guidance; Synthra does not
  install them automatically.

## Creating a custom Ollama model later

`Modelfile` contains the future Synthra system prompt and uses the default
Qwen model as its base. Model creation is intentionally not run by this
version. After pulling the base model, you can create the custom model later:

```bash
ollama create synthra -f Modelfile
```

Then select it by setting `SYNTHRA_MODEL=synthra`.

## Tests

```bash
python -m py_compile *.py
pytest -q
```

The API tests use FastAPI's local test client and mock Ollama; they do not
require an external or hosted model service.

## Adding a language later

Add a language entry to `LANGUAGE_RULES` in `languages.py`, including its
extensions, run and test guidance, package manager or build tool, and notes.
Add or update the command validation and test-selection rules in `safety.py`
and `tools.py`, then add extension-detection and safety tests.
