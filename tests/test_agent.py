from agent import (
    DEFAULT_MODEL,
    FALLBACK_MODEL,
    TOOL_DEFINITIONS,
    _execute_tool,
    _select_model,
    handle_request,
)


class LocalModels:
    def list(self) -> dict[str, list[dict[str, str]]]:
        return {"models": [{"name": FALLBACK_MODEL}]}


def test_default_model_falls_back_when_only_fallback_is_installed() -> None:
    assert _select_model(LocalModels(), DEFAULT_MODEL) == FALLBACK_MODEL


def test_agent_exposes_all_required_tools() -> None:
    tool_names = {tool["function"]["name"] for tool in TOOL_DEFINITIONS}

    assert tool_names == {
        "list_files",
        "read_file",
        "write_file",
        "run_command",
        "run_tests",
        "detect_language",
        "get_language_rules",
        "remember_fact",
        "recall_memory",
        "update_project_memory",
        "search_knowledge",
    }


def test_dry_run_previews_writes_without_writing_or_running_commands(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("dry run prompted")),
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dry run executed a command")
        ),
    )

    preview = _execute_tool(
        "write_file",
        {"path": "src/new.py", "content": "print('preview')"},
        dry_run=True,
    )
    command = _execute_tool(
        "run_command", {"command": "python app.py"}, dry_run=True
    )

    assert "would create file: src/new.py" in preview
    assert "print('preview')" in preview
    assert command == "Dry run: would run command: python app.py"
    assert not (tmp_path / "src/new.py").exists()


def test_agent_blocks_writes_until_project_and_language_are_inspected(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    class Client:
        def __init__(self) -> None:
            self.responses = iter(
                [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Plan: create a small file.",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "write_file",
                                        "arguments": {
                                            "path": "new.py",
                                            "content": "print('hello')",
                                        },
                                    }
                                }
                            ],
                        }
                    },
                    {
                        "message": {
                            "role": "assistant",
                            "content": "I need to inspect and detect the project first.",
                        }
                    },
                ]
            )

        def chat(self, **_kwargs):
            return next(self.responses)

    handle_request([], "Create a file", "local-model", Client())

    assert not (tmp_path / "new.py").exists()


def test_handle_request_returns_final_response_for_feedback() -> None:
    class Client:
        def chat(self, **_kwargs):
            return {"message": {"role": "assistant", "content": "The final answer."}}

    answer = handle_request([], "A request", "local-model", Client())

    assert answer == "The final answer."
