from agent import DEFAULT_MODEL, FALLBACK_MODEL, TOOL_DEFINITIONS, _select_model


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
    }
