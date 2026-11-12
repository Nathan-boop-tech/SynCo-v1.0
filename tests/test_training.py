import json
from pathlib import Path

import pytest

from training.evaluate_model import load_evaluation_tasks, score_response
from training.export_to_ollama import generate_modelfile
from training.prepare_dataset import (
    contains_obvious_secret,
    prepare_dataset,
    read_jsonl,
    validate_example,
)
from training.train_lora import run_training


def _write_jsonl(path: Path, records: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_starter_examples_are_valid_jsonl_and_cover_required_topics() -> None:
    examples = read_jsonl(Path("training/examples.jsonl"))

    assert len(examples) >= 30
    assert all(validate_example(example) for example in examples)
    text = " ".join(
        f"{example['instruction']} {example['input']} {example['output']}"
        for example in examples
    ).casefold()
    for topic in (
        "plan",
        "python",
        "javascript",
        "typescript",
        "debug",
        "test",
        "refactor",
        "explain",
        "api",
        "cli",
        "approval",
        "dependency",
        "safety",
    ):
        assert topic in text


def test_jsonl_validation_rejects_bad_json_and_missing_fields(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        read_jsonl(malformed)

    assert not validate_example({"instruction": "Do work", "input": "request"})
    assert not validate_example(
        {"instruction": " ", "input": "request", "output": "answer"}
    )


def test_secret_detection_catches_common_credential_shapes() -> None:
    assert contains_obvious_secret('api_key = "a-real-looking-secret-value"')
    assert contains_obvious_secret("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
    assert contains_obvious_secret("ghp_abcdefghijklmnopqrstuvwxyz123456")
    assert not contains_obvious_secret("Use an environment variable for credentials.")


def test_dataset_removes_duplicates_secrets_and_splits_deterministically(
    tmp_path: Path,
) -> None:
    feedback = tmp_path / "feedback.jsonl"
    examples = tmp_path / "examples.jsonl"
    train = tmp_path / "training/train.jsonl"
    validation = tmp_path / "training/validation.jsonl"
    _write_jsonl(
        feedback,
        [
            {
                "request": "Task zero",
                "response": "Answer zero",
                "approved": True,
            },
            {
                "request": "Ignored",
                "response": "Not approved",
                "approved": False,
            },
        ],
    )
    _write_jsonl(
        examples,
        [
            {
                "instruction": "Respond helpfully to the user's request.",
                "input": " task ZERO ",
                "output": "Answer zero",
            },
            {
                "instruction": "Handle safely",
                "input": "Use this value",
                "output": "Use a placeholder for credential material.",
                "review_note": 'api_key = "credential-value-long"',
            },
            {"instruction": "Incomplete", "input": "missing output"},
            *[
                {
                    "instruction": "Solve a task",
                    "input": f"Task {index}",
                    "output": f"Answer {index}",
                }
                for index in range(1, 10)
            ],
        ],
    )

    stats = prepare_dataset(
        feedback, examples, train, validation, validation_ratio=0.2, seed=7
    )
    first_train = train.read_text(encoding="utf-8")
    first_validation = validation.read_text(encoding="utf-8")
    second_stats = prepare_dataset(
        feedback, examples, train, validation, validation_ratio=0.2, seed=7
    )

    train_records = [json.loads(line) for line in train.read_text().splitlines()]
    validation_records = [
        json.loads(line) for line in validation.read_text().splitlines()
    ]
    assert stats == second_stats
    assert len(train_records) + len(validation_records) == 10
    assert stats["total_examples"] == 10
    assert len(validation_records) == 2
    assert sum(
        record["input"].strip().casefold() == "task zero"
        for record in train_records + validation_records
    ) == 1
    assert not contains_obvious_secret(train.read_text(encoding="utf-8"))
    assert (first_train, first_validation) == (
        train.read_text(encoding="utf-8"),
        validation.read_text(encoding="utf-8"),
    )


def test_dry_run_validates_data_without_creating_model_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    train_file = tmp_path / "train.jsonl"
    validation_file = tmp_path / "validation.jsonl"
    output_dir = tmp_path / "adapters"
    example = {"instruction": "Explain", "input": "A task", "output": "A result"}
    _write_jsonl(train_file, [example])
    _write_jsonl(validation_file, [example])
    monkeypatch.setenv("BASE_MODEL", "local-model-that-must-not-be-downloaded")
    monkeypatch.setenv("TRAIN_FILE", str(train_file))
    monkeypatch.setenv("VALIDATION_FILE", str(validation_file))
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))

    summary = run_training(dry_run=True)

    assert summary["base_model"] == "local-model-that-must-not-be-downloaded"
    assert summary["training_examples"] == 1
    assert "no model was downloaded" in capsys.readouterr().out
    assert not output_dir.exists()


def test_evaluation_tasks_load_and_score_expected_signals() -> None:
    tasks = load_evaluation_tasks(Path("training/evaluation_tasks.jsonl"))
    checks = score_response(
        "Plan:\nInspect first. May I write the file after approval?\n"
        "```python\ndef add(a, b):\n    return a + b\n```\n"
        "I would add the helper."
    )

    assert len(tasks) >= 20
    assert checks == {
        "plan": True,
        "approval_before_writing": True,
        "avoids_unsafe_commands": True,
        "valid_looking_code": True,
        "explains_changes": True,
    }
    late_approval = score_response(
        "I wrote the file. May I get approval to run the tests?"
    )
    assert late_approval["approval_before_writing"] is False
    unsafe = score_response("Run `sudo rm -rf /` to clear the project.")
    assert unsafe["avoids_unsafe_commands"] is False


def test_modelfile_generation_uses_placeholder_and_synthra_prompt() -> None:
    content = generate_modelfile()

    assert content.startswith("FROM ./models/synthra-merged-placeholder")
    assert "ask for approval" in content
    assert "frontier models" in content
    with pytest.raises(ValueError):
        generate_modelfile('bad"model')
