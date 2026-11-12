"""Validate, filter, deduplicate, and split Synthra JSONL examples."""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_FILE = ROOT / "feedback" / "good_examples.jsonl"
EXAMPLES_FILE = ROOT / "training" / "examples.jsonl"
TRAIN_FILE = ROOT / "training" / "train.jsonl"
VALIDATION_FILE = ROOT / "training" / "validation.jsonl"
REQUIRED_FIELDS = ("instruction", "input", "output")
DEFAULT_VALIDATION_RATIO = 0.1
DEFAULT_RANDOM_SEED = 42

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|"
               r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
    re.compile(r"\bsynthra_live_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}"),
    re.compile(
        r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|"
        r"client[_-]?secret)\s*[:=]\s*['\"]?[^'\"\s,;]{8,}",
        re.IGNORECASE,
    ),
)


def contains_obvious_secret(value: str) -> bool:
    """Return whether text contains a recognizable credential pattern."""
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        return True
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return False
    if isinstance(decoded, dict):
        return any(
            contains_obvious_secret(
                item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            )
            for item in decoded.values()
        )
    if isinstance(decoded, list):
        return any(
            contains_obvious_secret(
                item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            )
            for item in decoded
        )
    return False


def validate_example(record: Any) -> bool:
    """Accept only non-empty JSON objects with the required string fields."""
    return (
        isinstance(record, dict)
        and all(
            isinstance(record.get(field), str) and bool(record[field].strip())
            for field in REQUIRED_FIELDS
        )
    )


def read_jsonl(path: str | Path) -> list[Any]:
    """Read JSON objects from JSONL, reporting malformed lines with locations."""
    source = Path(path)
    if not source.exists():
        return []
    records: list[Any] = []
    try:
        with source.open(encoding="utf-8") as data_file:
            for line_number, line in enumerate(data_file, start=1):
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"Invalid JSON in {source}:{line_number}: {error.msg}"
                    ) from error
    except OSError as error:
        raise OSError(f"Could not read {source}: {error}") from error
    return records


def _feedback_to_example(record: Any) -> dict[str, str] | None:
    if not isinstance(record, dict) or record.get("approved") is not True:
        return None
    request = record.get("request")
    response = record.get("response")
    if not isinstance(request, str) or not isinstance(response, str):
        return None
    return {
        "instruction": "Respond helpfully to the user's request.",
        "input": request,
        "output": response,
    }


def _normalized_key(record: dict[str, str]) -> tuple[str, str, str]:
    return (
        " ".join(record["instruction"].split()).casefold(),
        " ".join(record["input"].split()).casefold(),
        " ".join(record["output"].split()).casefold(),
    )


def _write_jsonl(path: Path, records: list[dict[str, str]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as output_file:
            for record in records:
                output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        raise OSError(f"Could not write {path}: {error}") from error


def _example_from_record(record: Any) -> dict[str, str] | None:
    if not validate_example(record):
        return None
    example = {field: record[field].strip() for field in REQUIRED_FIELDS}
    if any(contains_obvious_secret(example[field]) for field in REQUIRED_FIELDS):
        return None
    return example


def prepare_dataset(
    feedback_path: str | Path = FEEDBACK_FILE,
    examples_path: str | Path = EXAMPLES_FILE,
    train_path: str | Path = TRAIN_FILE,
    validation_path: str | Path = VALIDATION_FILE,
    validation_ratio: float = DEFAULT_VALIDATION_RATIO,
    seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, float | int]:
    """Prepare a deterministic split and return counts and length statistics."""
    if not 0 <= validation_ratio < 1:
        raise ValueError("validation_ratio must be between 0 (inclusive) and 1 (exclusive)")

    accepted: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    sources = ((Path(feedback_path), True), (Path(examples_path), False))
    for path, is_feedback in sources:
        for record in read_jsonl(path):
            if contains_obvious_secret(json.dumps(record, ensure_ascii=False)):
                continue
            candidate = (
                _feedback_to_example(record)
                if is_feedback
                else record
            )
            example = _example_from_record(candidate)
            if example is None:
                continue
            key = _normalized_key(example)
            if key in seen:
                continue
            seen.add(key)
            accepted.append(example)

    shuffled = accepted[:]
    random.Random(seed).shuffle(shuffled)
    validation_count = (
        min(len(shuffled) - 1, max(1, round(len(shuffled) * validation_ratio)))
        if len(shuffled) > 1 and validation_ratio > 0
        else 0
    )
    if validation_count:
        train_records = shuffled[:-validation_count]
        validation_records = shuffled[-validation_count:]
    else:
        train_records = shuffled
        validation_records = []

    _write_jsonl(Path(train_path), train_records)
    _write_jsonl(Path(validation_path), validation_records)
    return {
        "total_examples": len(accepted),
        "training_examples": len(train_records),
        "validation_examples": len(validation_records),
        "average_input_length": (
            mean(len(record["input"]) for record in accepted) if accepted else 0.0
        ),
        "average_output_length": (
            mean(len(record["output"]) for record in accepted) if accepted else 0.0
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-ratio", type=float, default=DEFAULT_VALIDATION_RATIO)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    arguments = parser.parse_args(argv)
    statistics = prepare_dataset(
        validation_ratio=arguments.validation_ratio,
        seed=arguments.seed,
    )
    print(f"Total examples: {statistics['total_examples']}")
    print(f"Training examples: {statistics['training_examples']}")
    print(f"Validation examples: {statistics['validation_examples']}")
    print(f"Average input length: {statistics['average_input_length']:.1f} characters")
    print(f"Average output length: {statistics['average_output_length']:.1f} characters")


if __name__ == "__main__":
    main()
