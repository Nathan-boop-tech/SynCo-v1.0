"""Path and command checks for Synthra's project tools."""

import re
import shlex
from pathlib import Path
from typing import Iterable

BLOCKED_COMMAND_PARTS = (
    "rm -rf",
    "sudo",
    "chmod 777",
    "curl | sh",
    "wget | sh",
    "&&",
    ";",
)
_BLOCKED_PATH_PARTS = {".git"}
_BLOCKED_NAME_PARTS = (
    "secret",
    "credential",
    "password",
    "token",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "id_rsa",
)
_SHELL_SYNTAX = re.compile(r"[|><`\n\r]|&&|\|\||\$\(|\$\{")


def is_safe_path(path: str) -> bool:
    """Return whether a non-absolute path resolves inside the current project."""
    if not isinstance(path, str):
        return False
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False

    try:
        return candidate.resolve().is_relative_to(Path.cwd().resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def is_sensitive_path(path: str) -> bool:
    """Identify paths that might contain credentials or private keys."""
    if not isinstance(path, str):
        return True
    candidate = Path(path)
    parts = [part.lower() for part in candidate.parts]
    if any(part in _BLOCKED_PATH_PARTS for part in parts):
        return True
    for part in parts:
        if (
            part == ".env"
            or (part.startswith(".env.") and part != ".env.example")
            or any(marker in part for marker in _BLOCKED_NAME_PARTS)
        ):
            return True
        if part.endswith((".pem", ".key")) or part == "credentials":
            return True
    return False


def _safe_project_path_argument(argument: str) -> bool:
    """Reject explicit path-like command arguments that escape the project."""
    if argument.startswith("-") or not argument:
        return True
    path = Path(argument)
    if path.is_absolute() or ".." in path.parts:
        return False
    if "/" in argument or path.suffix:
        return is_safe_path(argument)
    return True


def _command_matches_language(parts: list[str], language: str) -> bool:
    """Check that the command belongs to one of the selected language toolchains."""
    executable = parts[0]
    arguments = parts[1:]
    first = arguments[0] if arguments else ""

    if executable in {"python", "python3", "pytest", "pip", "pip3"}:
        if executable == "pytest":
            return language == "Python"
        if executable in {"pip", "pip3"}:
            return language == "Python" and first == "install"
        if executable in {"python", "python3"}:
            if language in {"HTML", "CSS"}:
                return arguments[:2] == ["-m", "http.server"]
            if language != "Python":
                return False
            return first.endswith(".py") or (
                first == "-m"
                and len(arguments) > 1
                and arguments[1] in {"pytest", "unittest", "http.server"}
            )
        return False
    if executable == "node":
        return language in {"JavaScript", "TypeScript"} and bool(
            arguments
            and Path(arguments[0]).suffix
            in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
        )
    if executable == "npm":
        return language in {"JavaScript", "TypeScript"} and first in {
            "test",
            "run",
        } and len(arguments) >= 1
    if executable == "npx":
        return language == "TypeScript" and (
            arguments[:1] == ["tsx"]
            or arguments[:2] == ["--no-install", "tsx"]
            or arguments[:1] == ["tsc"]
            or arguments[:2] == ["--no-install", "tsc"]
        )
    if executable == "tsc":
        return language == "TypeScript"
    if executable in {"javac", "java"}:
        return language == "Java"
    if executable in {"mvn", "gradle"}:
        return language == "Java" and first in {"test", "build", "run"}
    if executable in {"./gradlew", "./mvnw", "mvnw"}:
        return language == "Java" and first in {"test", "build", "run"}
    if executable in {"gcc", "make", "cmake", "ctest"}:
        return language in {"C", "C++"}
    if executable == "g++":
        return language == "C++"
    if executable.startswith("./"):
        return (
            language in {"C", "C++"}
            and is_safe_path(executable)
            and Path(executable).is_file()
        )
    if executable == "dotnet":
        return language == "C#" and first in {"run", "test", "build"}
    if executable == "go":
        return language == "Go" and first in {"run", "test", "build"}
    if executable == "cargo":
        return language == "Rust" and first in {"run", "test", "build"}
    if executable == "swift":
        return language == "Swift" and first in {"run", "test"}
    if executable in {"sqlite3", "psql", "mysql"}:
        return language == "SQL" and any(
            re.match(r"\s*(select|explain|pragma)\b", item, re.IGNORECASE)
            for item in arguments
        )
    if executable == "bash":
        return language == "Bash" and (
            first == "-n"
            or bool(arguments and Path(first).suffix == ".sh")
        )
    if executable == "shellcheck":
        return language == "Bash"
    return False


def is_safe_command(command: str, languages: Iterable[str] | None = None) -> bool:
    """Validate a single, allowlisted command and optionally its project language."""
    if not isinstance(command, str) or not command.strip():
        return False
    normalized = command.lower()
    if any(blocked in normalized for blocked in BLOCKED_COMMAND_PARTS):
        return False
    if _SHELL_SYNTAX.search(command):
        return False

    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts or any(not _safe_project_path_argument(item) for item in parts[1:]):
        return False

    supported_languages = set(languages) if languages is not None else {
        "Python",
        "JavaScript",
        "TypeScript",
        "Java",
        "C",
        "C++",
        "C#",
        "Go",
        "Rust",
        "Swift",
        "SQL",
        "Bash",
    }
    return any(
        _command_matches_language(parts, language) for language in supported_languages
    )
