"""Approval-gated file and command tools for Synthra."""

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from languages import (
    LANGUAGE_RULES,
    detect_language as _detect_language,
    get_language_rules as _get_language_rules,
    project_languages,
)
from safety import is_safe_command, is_safe_path, is_sensitive_path

MAX_FILE_CHARS = 20_000
SKIP_DIRECTORIES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".env",
    ".venv",
    "env",
    "venv",
    "virtualenv",
}
_INSTALL_HINTS = {
    "python": "Install Python 3.11 or newer.",
    "python3": "Install Python 3.11 or newer.",
    "pytest": "Install pytest with `python -m pip install pytest` after approval.",
    "pip": "Install Python 3.11 or newer, which includes pip.",
    "pip3": "Install Python 3.11 or newer, which includes pip.",
    "node": "Install Node.js from its official distribution.",
    "npm": "Install Node.js; npm is included with standard Node.js installations.",
    "npx": "Install Node.js; npx is included with standard Node.js installations.",
    "tsc": "Install TypeScript in the project using npm after approval.",
    "javac": "Install a Java Development Kit (JDK).",
    "java": "Install a Java Runtime Environment or JDK.",
    "mvn": "Install Apache Maven or use a project Maven wrapper.",
    "gradle": "Install Gradle or use a project Gradle wrapper.",
    "./gradlew": "Add the project's Gradle wrapper or install Gradle.",
    "./mvnw": "Add the project's Maven wrapper or install Maven.",
    "mvnw": "Add the project's Maven wrapper or install Maven.",
    "gcc": "Install GCC or another C compiler.",
    "g++": "Install a C++ compiler such as GCC.",
    "make": "Install Make or use the project's documented build tool.",
    "cmake": "Install CMake.",
    "ctest": "Install CMake to provide CTest.",
    "dotnet": "Install the .NET SDK.",
    "go": "Install the Go toolchain.",
    "cargo": "Install Rust and Cargo using the official Rust toolchain installer.",
    "swift": "Install Swift for your operating system.",
    "sqlite3": "Install the SQLite command-line tools.",
    "psql": "Install the PostgreSQL client.",
    "mysql": "Install the MySQL client.",
    "bash": "Install Bash.",
    "shellcheck": "Install ShellCheck using your operating system's package manager.",
}


def detect_language(path: str) -> str:
    """Detect language from a file extension or summarize a project directory."""
    return _detect_language(path)


def get_language_rules(language: str) -> dict[str, Any] | str:
    """Get run, test, extension, package-manager, and notes for a language."""
    return _get_language_rules(language)


def list_files(path: str = ".") -> str:
    """List project files and folders, skipping repositories and environments."""
    if not is_safe_path(path):
        return f"Error: path is outside the project or uses traversal: {path}"

    target = Path(path).resolve()
    if not target.is_dir():
        return f"Error: not a directory: {path}"
    root = Path.cwd().resolve()
    entries: list[str] = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    try:
        for current, directories, filenames in os.walk(
            target, onerror=raise_walk_error
        ):
            directories[:] = sorted(
                name
                for name in directories
                if name not in SKIP_DIRECTORIES
                and not (Path(current) / name / "pyvenv.cfg").is_file()
            )
            current_path = Path(current)
            entries.extend(
                (current_path / name).relative_to(root).as_posix() + "/"
                for name in directories
            )
            entries.extend(
                (current_path / name).relative_to(root).as_posix()
                for name in sorted(filenames)
            )
    except OSError as error:
        return f"Error listing files in {path}: {error}"
    return "\n".join(sorted(entries)) if entries else "(no files found)"


def read_file(path: str) -> str:
    """Read a safe UTF-8 project file, limited to 20,000 characters."""
    if not is_safe_path(path):
        return f"Error: path is outside the project or uses traversal: {path}"
    if is_sensitive_path(path):
        return f"Error: refusing to read a potentially sensitive file: {path}"

    target = Path(path).resolve()
    if not target.is_file():
        return f"Error: not a file: {path}"
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return f"Error reading {path}: {error}"

    if len(content) > MAX_FILE_CHARS:
        return content[:MAX_FILE_CHARS] + "\n[truncated at 20,000 characters]"
    return content


def write_file(path: str, content: str) -> str:
    """Write a project file only after explicit user approval."""
    if not is_safe_path(path):
        return f"Error: path is outside the project or uses traversal: {path}"
    if is_sensitive_path(path):
        return f"Error: refusing to write a potentially sensitive file: {path}"
    if not isinstance(content, str):
        return "Error: file content must be a string."

    target = Path(path).resolve()
    if target.exists() and not target.is_file():
        return f"Error: not a file: {path}"

    preview = content[:500]
    if len(content) > 500:
        preview += "\n[preview truncated]"
    print(f"Requested write: {path}\n--- Preview ---\n{preview}\n---")
    approval = input("Allow Synthra to write this file? (yes/no) ").strip().lower()
    if approval not in {"yes", "y"}:
        return f"Write denied by user: {path}"

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as error:
        return f"Error writing {path}: {error}"
    return f"File written: {path}"


def _missing_tool_message(command: str, language: str) -> str | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return "Error: could not parse the command."
    executable = parts[0]
    if shutil.which(executable) is None:
        hint = _INSTALL_HINTS.get(executable, f"Install the {language} toolchain.")
        return f"Required tool '{executable}' is not installed. {hint}"

    if executable in {"python", "python3"} and len(parts) > 2:
        if parts[1] == "-m" and parts[2] == "pytest":
            try:
                if importlib.util.find_spec("pytest") is None:
                    return (
                        "pytest is not installed for this Python interpreter. "
                        "Install it with `python -m pip install pytest` after approval."
                    )
            except (ImportError, ValueError):
                return "Could not verify pytest availability in this Python environment."

    if executable == "npm" and parts[1:2] in (["test"], ["run"]):
        package_file = Path("package.json")
        if not package_file.is_file():
            return "This JavaScript project has no package.json test configuration."
        try:
            package_data = json.loads(package_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return f"Could not read package.json: {error}"
        script_name = "test" if parts[1] == "test" else parts[2] if len(parts) > 2 else ""
        scripts = package_data.get("scripts", {}) if isinstance(package_data, dict) else {}
        if not isinstance(scripts, dict) or not isinstance(scripts.get(script_name), str):
            return f"No '{script_name or 'named'}' script is configured in package.json."
    if executable == "npx":
        arguments = parts[1:]
        tool_name = (
            arguments[1]
            if arguments[:1] == ["--no-install"] and len(arguments) > 1
            else arguments[0] if arguments else ""
        )
        local_tool = Path("node_modules/.bin") / tool_name
        if tool_name and not local_tool.exists() and shutil.which(tool_name) is None:
            return (
                f"The TypeScript tool '{tool_name}' is not installed in this project. "
                "Install it with npm after approval."
            )
    return None


def run_command(command: str) -> str:
    """Run one language-relevant command after validating and asking approval."""
    languages = project_languages()
    if not languages:
        return "Error: no supported project language was detected; refusing to run a command."
    if not is_safe_command(command, languages):
        return (
            "Error: command is not allowed or is not relevant to the detected project "
            f"languages ({', '.join(languages)}): {command}"
        )

    missing_tool = _missing_tool_message(command, languages[0])
    if missing_tool:
        return missing_tool

    approval = input(f"Allow Synthra to run this command? (yes/no) {command}\n").strip().lower()
    if approval not in {"yes", "y"}:
        return f"Command denied by user: {command}"

    try:
        result = subprocess.run(
            shlex.split(command),
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        return (
            f"Command timed out after 60 seconds: {command}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
    except OSError as error:
        return f"Error running command {command}: {error}"

    return (
        f"Command executed: {command}\n"
        f"Exit code: {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def _project_files() -> list[Path]:
    root = Path.cwd()
    files: list[Path] = []
    for current, directories, filenames in os.walk(root):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in SKIP_DIRECTORIES
            and not (Path(current) / directory / "pyvenv.cfg").is_file()
        )
        files.extend(Path(current) / filename for filename in filenames)
    return files


def _test_command(language: str, files: list[Path]) -> str | None:
    """Choose a project test command only when its required setup is present."""
    root_files = {file.name.lower() for file in files if file.parent == Path.cwd()}
    if language == "Python":
        has_tests = any(
            "test" in file.parts
            or file.name.startswith("test_")
            or file.name.endswith("_test.py")
            for file in files
            if file.suffix == ".py"
        )
        if has_tests:
            return "python -m pytest -q"
        return None
    if language in {"JavaScript", "TypeScript"}:
        package = Path("package.json")
        if package.is_file():
            try:
                metadata = json.loads(package.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return None
            if isinstance(metadata, dict) and isinstance(
                metadata.get("scripts", {}).get("test"), str
            ):
                return "npm test"
        return None
    if language == "Java":
        if "pom.xml" in root_files:
            return "mvn test" if shutil.which("mvn") else None
        if any(name in root_files for name in {"build.gradle", "build.gradle.kts"}):
            if Path("gradlew").is_file() and os.access("gradlew", os.X_OK):
                return "./gradlew test"
            return "gradle test" if shutil.which("gradle") else None
        return None
    if language == "C#":
        if any(file.suffix.lower() in {".csproj", ".sln"} for file in files):
            return "dotnet test"
        return None
    if language == "Go":
        if "go.mod" in root_files or any(file.name.endswith("_test.go") for file in files):
            return "go test ./..."
        return None
    if language == "Rust":
        return "cargo test" if "cargo.toml" in root_files else None
    if language == "Swift":
        return "swift test" if "package.swift" in root_files else None
    if language in {"C", "C++"}:
        if "makefile" in root_files:
            return "make test"
        if "cmakelists.txt" in root_files and Path("build/CTestTestfile.cmake").is_file():
            return "ctest --test-dir build --output-on-failure"
        return None
    if language == "Bash":
        scripts = sorted(file for file in files if file.suffix.lower() in {".sh", ".bash"})
        if scripts:
            script = scripts[0].relative_to(Path.cwd()).as_posix()
            return f"shellcheck {shlex.quote(script)}" if shutil.which("shellcheck") else f"bash -n {shlex.quote(script)}"
        return None
    return None


def run_tests(language: str) -> str:
    """Find and run the project's appropriate tests after explicit approval."""
    rules = get_language_rules(language)
    if not isinstance(rules, dict):
        return str(rules)
    canonical_language = rules["name"]
    files = _project_files()
    command = _test_command(canonical_language, files)
    if command is None:
        if canonical_language in {"HTML", "CSS"}:
            return "No standard automated test command exists for this language; use a browser or project-specific checks."
        if canonical_language == "SQL":
            return "SQL tests depend on the database and project framework; no database-specific test command was inferred."
        return (
            f"No configured test command or test setup was found for {canonical_language}. "
            "Add the relevant project test configuration first."
        )
    return run_command(command)
