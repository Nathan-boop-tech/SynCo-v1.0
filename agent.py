"""Synthra, a local multi-language coding agent powered by Ollama."""

import argparse
import json
import os
from typing import Any

import ollama

import tools as project_tools
from save_training_example import convert_approved_feedback

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
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Save a project fact in persistent memory after user approval.",
            "parameters": {
                "type": "object",
                "properties": {"fact": {"type": "string"}},
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Recall project facts and notes relevant to a topic.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_project_memory",
            "description": "Update a supported project-memory topic after user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["topic", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the project's local knowledge files before answering difficult questions.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
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
    "remember_fact": project_tools.remember_fact,
    "recall_memory": project_tools.recall_memory,
    "update_project_memory": project_tools.update_project_memory,
    "search_knowledge": project_tools.search_knowledge,
}
MUTATING_TOOLS = {
    "write_file",
    "run_command",
    "run_tests",
    "remember_fact",
    "update_project_memory",
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


def _execute_tool(name: str, raw_arguments: Any, dry_run: bool = False) -> str:
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return f"Error: unknown tool: {name}"
    try:
        arguments = _tool_arguments(raw_arguments)
        if dry_run and name in MUTATING_TOOLS:
            if name == "write_file":
                return project_tools.preview_write_file(**arguments)
            if name == "run_command":
                return f"Dry run: would run command: {arguments.get('command', '')}"
            if name == "run_tests":
                return f"Dry run: would run tests for {arguments.get('language', '')}."
            if name == "remember_fact":
                return (
                    "Dry run: would save this fact to memory/project_memory.json: "
                    f"{arguments.get('fact', '')}"
                )
            return (
                "Dry run: would update memory/project_memory.json topic "
                f"{arguments.get('topic', '')} with: {arguments.get('content', '')}"
            )
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
        "3. Read the necessary files, make a short `Plan:`, and ask for approval before changes or commands.\n"
        "4. Make approved changes, then run tests and read their errors; fix mistakes and retest.\n"
        "5. Search the knowledge files with search_knowledge before answering difficult project questions.\n"
        "6. Use only the detected language's toolchain; explain missing tools without installing them.\n"
        "7. Finish with what changed, files, commands, errors, and what to check next.\n"
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


def _call_tool(
    call: Any, dry_run: bool = False, blocked_reason: str | None = None
) -> tuple[str, str, str]:
    function_call = _value(call, "function", {})
    name = _value(function_call, "name", "")
    raw_arguments = _value(function_call, "arguments", {})
    print(f"Synthra wants to use tool: {name}")
    try:
        arguments = _tool_arguments(raw_arguments)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return name, "{}", f"Error: invalid arguments for {name}: {error}"
    if blocked_reason:
        return name, json.dumps(arguments, ensure_ascii=False), blocked_reason
    result = _execute_tool(name, arguments, dry_run=dry_run)
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
        elif name == "write_file" and result.startswith("Dry run: would "):
            changed_files.append(result.splitlines()[0].removeprefix("Dry run: would "))
        elif name in {"remember_fact", "update_project_memory"}:
            if result.startswith("Project memory updated: "):
                changed_files.append(result.removeprefix("Project memory updated: "))
            elif result.startswith("Dry run: would "):
                changed_files.append("memory/project_memory.json (dry-run preview)")
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
    history: list[dict[str, Any]],
    user_text: str,
    model: str,
    client: Any,
    dry_run: bool = False,
) -> str:
    """Handle a request, executing at most ten model tool-call rounds."""
    model_user_text = user_text
    if dry_run:
        files = project_tools.list_files(".")
        languages = project_tools.detect_language(".")
        print(f"\n--- Dry-run project inspection ---\n{files}")
        print(f"Detected languages: {languages}")
        model_user_text = (
            f"{user_text}\n\n"
            "Dry-run preflight (already inspected; do not write files or run commands):\n"
            f"Project files:\n{files}\nDetected languages: {languages}"
        )
    history.append({"role": "user", "content": model_user_text})
    results: list[tuple[str, str, str]] = []
    project_inspected = dry_run
    language_detected = dry_run
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
            return answer

        message = _value(response, "message", {})
        history.append(_message_dict(message))
        calls = _tool_calls(message)
        if not calls:
            answer = _value(message, "content", "") or ""
            if answer:
                print(f"\nSynthra: {answer}")
            _print_summary(results, answer, round_limit_reached=False)
            return answer

        content = _value(message, "content", "") or ""
        if content:
            print(f"\nSynthra: {content}")
            plan_presented = plan_presented or "plan:" in content.lower()
        for call in calls:
            requested_name = _value(
                _value(call, "function", {}), "name", ""
            )
            blocked_reason = None
            if requested_name in {"write_file", "run_command", "run_tests"}:
                if not project_inspected:
                    blocked_reason = (
                        "Error: inspect the project with list_files before making "
                        "changes or running commands."
                    )
                elif not language_detected:
                    blocked_reason = (
                        "Error: detect the project language before making changes "
                        "or running commands."
                    )
                elif not plan_presented:
                    blocked_reason = (
                        "Error: state a short Plan: before requesting a write or command."
                    )
            name, argument_json, result = _call_tool(call, dry_run, blocked_reason)
            if name == "list_files" and not result.startswith("Error:"):
                project_inspected = True
            elif name == "detect_language" and not result.startswith("Error:"):
                language_detected = True
            results.append((name, argument_json, result))
            print(f"Tool result:\n{result}")
            history.append({"role": "tool", "name": name, "content": result})

    answer = "I stopped because this request reached the tool-call round limit."
    print(f"\nSynthra: {answer}")
    _print_summary(results, answer, round_limit_reached=True)
    return answer


def _handle_feedback_command(
    command: str,
    last_request: str,
    last_response: str,
    dry_run: bool = False,
) -> bool:
    if command not in {"/good", "/bad", "/save-example"}:
        return False
    if dry_run:
        print("Dry run: feedback commands do not write files.")
        return True
    if not last_request or not last_response:
        print("There is no completed request and response to save yet.")
        return True
    if command == "/good":
        print(project_tools.save_good_feedback(last_request, last_response))
    elif command == "/bad":
        reason = input("What was wrong with Synthra's response? ").strip()
        if not reason:
            print("Bad feedback was not saved because no explanation was provided.")
            return True
        print(project_tools.save_bad_feedback(last_request, last_response, reason))
    else:
        approval = input("Save the last interaction as a training example? (yes/no) ")
        if approval.strip().lower() not in {"yes", "y"}:
            print("Training example not saved.")
            return True
        saved = project_tools.save_good_feedback(last_request, last_response)
        print(saved)
        if saved.startswith("Saved "):
            try:
                count = convert_approved_feedback()
            except (OSError, ValueError) as error:
                print(f"Error creating training example: {error}")
            else:
                print(f"Created {count} training example(s).")
    return True


def main(argv: list[str] | None = None) -> None:
    """Run Synthra's interactive terminal chat."""
    parser = argparse.ArgumentParser(description="Run the local Synthra coding agent.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="inspect and preview planned changes without writing files or running commands",
    )
    arguments = parser.parse_args(argv)
    requested_model = os.environ.get("SYNTHRA_MODEL", DEFAULT_MODEL)
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    client = ollama.Client(host=host)
    try:
        system_prompt = _system_prompt()
    except OSError as error:
        raise SystemExit(f"Could not load SYNTHRA.md: {error}") from error
    history: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    model = _select_model(client, requested_model)

    mode = " (dry-run: no files will be written and no commands will run)" if arguments.dry_run else ""
    print(f"Synthra is ready (local Ollama model: {model}){mode}. Type /exit to quit.")
    last_request = ""
    last_response = ""
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
        if _handle_feedback_command(
            user_text, last_request, last_response, dry_run=arguments.dry_run
        ):
            continue
        last_request = user_text
        last_response = handle_request(
            history, user_text, model, client, dry_run=arguments.dry_run
        )


if __name__ == "__main__":
    main()
