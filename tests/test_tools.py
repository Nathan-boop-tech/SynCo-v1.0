from pathlib import Path

import pytest

from tools import list_files, read_file, write_file


def test_list_files_skips_generated_and_git_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("", encoding="utf-8")

    result = list_files()

    assert "src/" in result
    assert "src/main.py" in result
    assert ".git" not in result
    assert "node_modules" not in result


def test_read_file_returns_content_and_blocks_unsafe_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")

    assert read_file("README.md") == "hello"
    assert read_file("../outside.md").startswith("Error: path is outside")
    assert read_file(".env").startswith("Error: refusing to read")


def test_read_file_truncates_long_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "large.txt").write_text("x" * 20_001, encoding="utf-8")

    result = read_file("large.txt")

    assert len(result.split("\n[truncated")[0]) == 20_000
    assert result.endswith("[truncated at 20,000 characters]")


def test_write_file_writes_only_after_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    prompts: list[str] = []

    def approve(prompt: str) -> str:
        prompts.append(prompt)
        return "yes"

    monkeypatch.setattr("builtins.input", approve)

    result = write_file("src/new.py", "print('hello')")

    assert result == "File written: src/new.py"
    assert (tmp_path / "src/new.py").read_text(encoding="utf-8") == "print('hello')"
    assert prompts == ["Allow Synthra to write this file? (yes/no) "]
    assert "Requested write: src/new.py" in capsys.readouterr().out
