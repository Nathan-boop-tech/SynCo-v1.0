from pathlib import Path

import pytest

from languages import LANGUAGE_RULES, detect_language, get_language_rules


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("main.py", "Python"),
        ("main.js", "JavaScript"),
        ("main.ts", "TypeScript"),
        ("index.html", "HTML"),
        ("site.css", "CSS"),
        ("Main.java", "Java"),
        ("main.c", "C"),
        ("main.cpp", "C++"),
        ("Program.cs", "C#"),
        ("main.go", "Go"),
        ("main.rs", "Rust"),
        ("main.swift", "Swift"),
        ("query.sql", "SQL"),
        ("script.sh", "Bash"),
    ],
)
def test_detect_language_by_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, expected: str
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / filename).touch()

    assert detect_language(filename) == expected


def test_project_detection_reports_multiple_languages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.py").touch()
    (tmp_path / "main.ts").touch()

    result = detect_language(".")

    assert "Multiple languages detected" in result
    assert "Python" in result
    assert "TypeScript" in result


def test_detection_uses_extension_for_a_new_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert detect_language("new_file.rs") == "Rust"


def test_every_language_has_documented_rules() -> None:
    expected_fields = {
        "name",
        "file_extensions",
        "run_command",
        "test_command",
        "package_manager",
        "notes",
    }

    assert len(LANGUAGE_RULES) == 14
    assert all(expected_fields <= rules.keys() for rules in LANGUAGE_RULES.values())
    assert get_language_rules("python")["name"] == "Python"
