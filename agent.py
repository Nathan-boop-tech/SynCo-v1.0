"""Synthra, a local multi-language coding agent powered by Ollama."""

import json
import os
from typing import Any

import ollama

import tools as project_tools

DEFAULT_MODEL = "qwen2.5-coder:7b"
FALLBACK_MODEL = "llama3.2:3b"
MAX_TOOL_ROUNDS = 10
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Inspect project files and folders before making a plan.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a non-sensitive UTF-8 project file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or update a safe project file after asking the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a language-relevant allowlisted command after approval.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the configured project tests for a detected language after approval.",
            "parameters": {
                "type": "object",
                "properties": {"language": {"type": "string"}},
                "required": ["language"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_language",
            "description": "Detect a file's language or languages present in a project folder.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_language_rules",
            "description": "Get extensions, run/test commands, package manager, and notes for a language.",
            "parameters": {
                "type": "object",
                "properties": {"language": {"type": "string"}},
                "required": ["language"],
            },
        },
    },
]
TOOL_FUNCTIONS = {
    "list_files": project_tools.list_files,
    "read_file": project_tools.read_file,
    "write_file": project_tools.write_file,
    "run_command": project_tools.run_command,
    "run_tests": project_tools.run_tests,
    "detect_language": project_tools.detect_language,
    "get_language_rules": project_tools.get_language_rules,
}


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        parsed = json.loads(raw_arguments)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("tool arguments must be a JSON object")


def _execute_tool(name: str, raw_arguments: Any) -> str:
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return f"Error: unknown tool: {name}"
    try:
        arguments = _tool_arguments(raw_arguments)
        result = function(**arguments)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return f"Error: invalid arguments for {name}: {error}"
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


def _system_prompt() -> str:
    with open("SYNTHRA.md", encoding="utf-8") as config_file:
        personality = config_file.read()
    return (
        f"{personality}\n\n"
        "Workflow for each coding request:\n"
        "1. Inspect the project with list_files and detect_language before proposing edits.\n"
        "2. If multiple languages are relevant and the request does not identify one, ask the user.\n"
        "3. Read the necessary files and state a short `Plan:` before requesting any write or command.\n"
        "4. Use only the detected language's toolchain; explain missing tools without installing them.\n"
        "5. After approved edits, run the appropriate tests when configured, inspect failures, and make focused fixes.\n"
        "6. Finish with what changed, files, commands, errors, and what to check next.\n"
        "Do not claim an action succeeded unless its tool reports success. "
        "Respect explicit requests not to use tools."
    )


def _tool_calls(message: Any) -> list[Any]:
    return _value(message, "tool_calls", []) or []


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    return {
        "role": _value(message, "role", "assistant"),
        "content": _value(message, "content", ""),
        "tool_calls": _tool_calls(message),
    }


def _call_tool(call: Any) -> tuple[str, str, str]:
    function_call = _value(call, "function", {})
    name = _value(function_call, "name", "")
    raw_arguments = _value(function_call, "arguments", {})
    print(f"Synthra wants to use tool: {name}")
    try:
        arguments = _tool_arguments(raw_arguments)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return name, "{}", f"Error: invalid arguments for {name}: {error}"
    result = _execute_tool(name, arguments)
    return name, json.dumps(arguments, ensure_ascii=False), result


def _print_summary(
    results: list[tuple[str, str, str]],
    final_answer: str,
    round_limit_reached: bool,
) -> None:
    changed_files: list[str] = []
    commands_run: list[str] = []
    errors: list[str] = []
    for name, _argument_json, result in results:
        if name == "write_file" and result.startswith("File written: "):
            changed_files.append(result.removeprefix("File written: "))
        if name in {"run_command", "run_tests"}:
            command_line = next(
                (line for line in result.splitlines() if line.startswith("Command executed: ")),
                None,
            )
            if command_line:
                command = command_line.removeprefix("Command executed: ")
                commands_run.append(command)
                exit_line = next(
                    (line for line in result.splitlines() if line.startswith("Exit code: ")),
                    "Exit code: unknown",
                )
                if exit_line != "Exit code: 0":
                    errors.append(f"{command}: {exit_line}")
            elif result.startswith("Command timed out after 60 seconds: "):
                commands_run.append(
                    result.splitlines()[0].removeprefix(
                        "Command timed out after 60 seconds: "
                    )
                )
        if result.lower().startswith("error") or "timed out" in result.lower():
            errors.append(result.splitlines()[0])

    print("\n--- Synthra summary ---")
    print(f"What was done: {final_answer or '(no final response returned)'}")
    print(f"Files changed: {', '.join(changed_files) if changed_files else 'None'}")
    print(f"Commands run: {', '.join(commands_run) if commands_run else 'None'}")
    print(f"Errors found: {'; '.join(errors) if errors else 'None'}")
    if round_limit_reached:
        print(
            "What to check next: Continue the request; "
            f"the {MAX_TOOL_ROUNDS}-round tool limit was reached."
        )
    else:
        print("What to check next: Review the changes and command output above.")


def _available_model_names(response: Any) -> set[str]:
    models = _value(response, "models", []) or []
    names: set[str] = set()
    for model in models:
        name = _value(model, "name") or _value(model, "model")
        if isinstance(name, str):
            names.add(name)
    return names


def _select_model(client: Any, requested_model: str) -> str:
    """Use the smaller local fallback when the default model is not installed."""
    if requested_model != DEFAULT_MODEL:
        return requested_model
    try:
        available = _available_model_names(client.list())
    except (ollama.RequestError, ollama.ResponseError):
        return requested_model
    if requested_model in available:
        return requested_model
    if FALLBACK_MODEL in available:
        print(
            f"{DEFAULT_MODEL} is not available locally; "
            f"using installed fallback {FALLBACK_MODEL}."
        )
        return FALLBACK_MODEL
    return requested_model


def handle_request(
    history: list[dict[str, Any]], user_text: str, model: str, client: Any
) -> None:
    """Handle a request, executing at most ten model tool-call rounds."""
    history.append({"role": "user", "content": user_text})
    results: list[tuple[str, str, str]] = []
    project_inspected = False
    language_detected = False
    plan_presented = False
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = client.chat(
                model=model,
                messages=history,
                tools=TOOL_DEFINITIONS,
            )
        except (ollama.RequestError, ollama.ResponseError) as error:
            if model == DEFAULT_MODEL:
                try:
                    fallback_available = (
                        FALLBACK_MODEL in _available_model_names(client.list())
                    )
                except (ollama.RequestError, ollama.ResponseError):
                    fallback_available = False
                if fallback_available:
                    print(
                        f"\n{DEFAULT_MODEL} could not be used; "
                        f"retrying with local model {FALLBACK_MODEL}."
                    )
                    model = FALLBACK_MODEL
                    continue
            answer = f"Ollama error: {error}"
            print(f"\n{answer}")
            results.append(("ollama", "{}", f"Error: {answer}"))
            _print_summary(results, answer, round_limit_reached=False)
            return

        message = _value(response, "message", {})
        history.append(_message_dict(message))
        calls = _tool_calls(message)
        if not calls:
            answer = _value(message, "content", "") or ""
            if answer:
                print(f"\nSynthra: {answer}")
            _print_summary(results, answer, round_limit_reached=False)
            return

        content = _value(message, "content", "") or ""
        if content:
            print(f"\nSynthra: {content}")
            plan_presented = plan_presented or "plan:" in content.lower()
        for call in calls:
            name, argument_json, result = _call_tool(call)
            if name == "list_files" and not result.startswith("Error:"):
                project_inspected = True
            elif name == "detect_language" and not result.startswith("Error:"):
                language_detected = True
            if name in {"write_file", "run_command", "run_tests"}:
                if not project_inspected:
                    result = "Error: inspect the project with list_files before making changes or running commands."
                elif not language_detected:
                    result = "Error: detect the project language before making changes or running commands."
                elif not plan_presented:
                    result = "Error: state a short Plan: before requesting a write or command."
            results.append((name, argument_json, result))
            print(f"Tool result:\n{result}")
            history.append({"role": "tool", "name": name, "content": result})

    answer = "I stopped because this request reached the tool-call round limit."
    print(f"\nSynthra: {answer}")
    _print_summary(results, answer, round_limit_reached=True)


def main() -> None:
    """Run Synthra's interactive terminal chat."""
    requested_model = os.environ.get("SYNTHRA_MODEL", DEFAULT_MODEL)
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    client = ollama.Client(host=host)
    try:
        system_prompt = _system_prompt()
    except OSError as error:
        raise SystemExit(f"Could not load SYNTHRA.md: {error}") from error
    history: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    model = _select_model(client, requested_model)

    print(f"Synthra is ready (local Ollama model: {model}). Type /exit to quit.")
    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return
        if user_text.lower() in {"/exit", "exit", "quit"}:
            print("Goodbye.")
            return
        if not user_text:
            continue
        handle_request(history, user_text, model, client)


if __name__ == "__main__":
    main()
