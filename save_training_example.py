"""Convert approved feedback records into local training-data examples."""

import json
from pathlib import Path
from typing import Any

from safety import is_safe_path


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as feedback_file:
            for line_number, line in enumerate(feedback_file, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"{path}:{line_number}: expected a JSON object")
                records.append(record)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON Lines data in {path}: {error}") from error
    return records


def convert_approved_feedback(
    feedback_directory: str | Path = "feedback",
    output_path: str | Path = "training_data/examples.jsonl",
) -> int:
    """Append each approved feedback pair once and return the number added."""
    feedback_dir = Path(feedback_directory)
    output = Path(output_path)
    sources = (
        feedback_dir / "good_examples.jsonl",
        feedback_dir / "bad_examples.jsonl",
    )
    if not is_safe_path(output.as_posix()) or any(
        not is_safe_path(source.as_posix()) for source in sources
    ):
        raise ValueError("Feedback and training-data paths must stay inside the project.")
    existing: set[tuple[str, str, str]] = set()
    if output.exists():
        for record in _read_records(output):
            if all(isinstance(record.get(key), str) for key in ("instruction", "input", "output")):
                existing.add((record["instruction"], record["input"], record["output"]))

    examples: list[dict[str, str]] = []
    instruction = "Respond helpfully to the user's request."
    for source in sources:
        for record in _read_records(source):
            request = record.get("request")
            response = record.get("response")
            if record.get("approved") is not True:
                continue
            if not isinstance(request, str) or not request.strip():
                continue
            if not isinstance(response, str) or not response.strip():
                continue
            key = (instruction, request, response)
            if key in existing:
                continue
            existing.add(key)
            examples.append(
                {"instruction": instruction, "input": request, "output": response}
            )

    if examples:
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open("a", encoding="utf-8") as training_file:
                for example in examples:
                    training_file.write(json.dumps(example, ensure_ascii=False) + "\n")
        except OSError as error:
            raise OSError(f"Could not write training examples to {output}: {error}") from error
    return len(examples)


if __name__ == "__main__":
    print(f"Created {convert_approved_feedback()} training example(s).")
