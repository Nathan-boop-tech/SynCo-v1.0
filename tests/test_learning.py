import json
from pathlib import Path

import pytest

from agent import _handle_feedback_command
from save_training_example import convert_approved_feedback
from tools import (
    recall_memory,
    remember_fact,
    save_bad_feedback,
    save_good_feedback,
    search_knowledge,
    update_project_memory,
)


def test_memories_can_be_saved_and_recalled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")

    assert update_project_memory("project_name", "Example Project").startswith(
        "Project memory updated:"
    )
    assert update_project_memory("known_bugs", "Parser fails on empty input").startswith(
        "Project memory updated:"
    )
    assert remember_fact("The API is local-only.").startswith("Project memory updated:")

    project = recall_memory("project name")
    bug = recall_memory("empty input")
    facts = recall_memory("local-only")

    assert "Example Project" in project
    assert "Parser fails on empty input" in bug
    assert "The API is local-only." in facts
    saved = json.loads((tmp_path / "memory/project_memory.json").read_text())
    assert saved["known_bugs"] == ["Parser fails on empty input"]


def test_search_knowledge_finds_matching_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "coding_rules.md").write_text(
        "# Rules\nAlways run focused tests before reporting.\n", encoding="utf-8"
    )
    (knowledge / "project_notes.md").write_text(
        "This unrelated note discusses project setup.\n", encoding="utf-8"
    )
    (knowledge / "app_apis.md").write_text("# API\n", encoding="utf-8")

    result = search_knowledge("focused tests")

    assert "coding_rules.md:2: Always run focused tests before reporting." in result
    assert "project_notes.md" not in result


def test_good_and_bad_feedback_are_saved_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert save_good_feedback("Add a test", "Added a focused test.") == (
        "Saved good feedback: feedback/good_examples.jsonl"
    )
    assert save_bad_feedback("Fix a bug", "The bug is fixed.", "It missed an edge case.") == (
        "Saved bad feedback: feedback/bad_examples.jsonl"
    )

    good = json.loads((tmp_path / "feedback/good_examples.jsonl").read_text())
    bad = json.loads((tmp_path / "feedback/bad_examples.jsonl").read_text())
    assert good["request"] == "Add a test"
    assert good["approved"] is True
    assert bad["reason"] == "It missed an edge case."
    assert bad["approved"] is False


def test_bad_command_collects_reason_before_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    prompts: list[str] = []

    def explain(prompt: str) -> str:
        prompts.append(prompt)
        return "It ignored the requested edge case."

    monkeypatch.setattr("builtins.input", explain)

    handled = _handle_feedback_command(
        "/bad", "Fix the parser", "The parser is fixed."
    )

    record = json.loads((tmp_path / "feedback/bad_examples.jsonl").read_text())
    assert handled is True
    assert prompts == ["What was wrong with Synthra's response? "]
    assert record["reason"] == "It ignored the requested edge case."


def test_training_examples_include_only_approved_feedback_and_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    save_good_feedback("Explain this function", "It adds two values.")
    save_bad_feedback("Write unsafe code", "Here is unsafe code.", "Not safe.")

    assert convert_approved_feedback() == 1
    assert convert_approved_feedback() == 0

    training = [
        json.loads(line)
        for line in (tmp_path / "training_data/examples.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert training == [
        {
            "instruction": "Respond helpfully to the user's request.",
            "input": "Explain this function",
            "output": "It adds two values.",
        }
    ]
