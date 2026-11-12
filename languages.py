"""Language detection and toolchain guidance for Synthra."""

import os
from pathlib import Path
from typing import Any

LANGUAGE_RULES: dict[str, dict[str, Any]] = {
    "Python": {
        "name": "Python",
        "file_extensions": [".py"],
        "run_command": "python <file.py>",
        "test_command": "python -m pytest",
        "package_manager": "pip",
        "notes": "Requires Python; pytest is optional and must be installed for pytest tests.",
    },
    "JavaScript": {
        "name": "JavaScript",
        "file_extensions": [".js", ".jsx", ".mjs", ".cjs"],
        "run_command": "node <file.js>",
        "test_command": "npm test",
        "package_manager": "npm",
        "notes": "Requires Node.js; npm test needs a test script in package.json.",
    },
    "TypeScript": {
        "name": "TypeScript",
        "file_extensions": [".ts", ".tsx"],
        "run_command": "npx --no-install tsx <file.ts> or tsc",
        "test_command": "npm test",
        "package_manager": "npm",
        "notes": "Requires Node.js and project-installed tsx/TypeScript tools.",
    },
    "HTML": {
        "name": "HTML",
        "file_extensions": [".html", ".htm"],
        "run_command": "Open the file in a browser; optionally use a local preview server.",
        "test_command": "No standard test command; use a browser or project-specific checks.",
        "package_manager": "None",
        "notes": "A browser is needed for visual preview; HTML has no standard package manager.",
    },
    "CSS": {
        "name": "CSS",
        "file_extensions": [".css"],
        "run_command": "Open its HTML page in a browser.",
        "test_command": "No standard test command; use a browser or project-specific checks.",
        "package_manager": "None",
        "notes": "A browser is needed for visual preview; CSS has no standard package manager.",
    },
    "Java": {
        "name": "Java",
        "file_extensions": [".java"],
        "run_command": "javac <file.java> then java <ClassName>",
        "test_command": "mvn test or gradle test",
        "package_manager": "Maven or Gradle",
        "notes": "Requires a JDK; Maven/Gradle tests require a matching project build file.",
    },
    "C": {
        "name": "C",
        "file_extensions": [".c"],
        "run_command": "gcc <file.c> -o <program>, then run <program>",
        "test_command": "make test or ctest",
        "package_manager": "Make or CMake",
        "notes": "Requires GCC or another C compiler; test targets are project-specific.",
    },
    "C++": {
        "name": "C++",
        "file_extensions": [".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"],
        "run_command": "g++ <file.cpp> -o <program>, then run <program>",
        "test_command": "make test or ctest",
        "package_manager": "CMake or Make",
        "notes": "Requires a C++ compiler; test targets are project-specific.",
    },
    "C#": {
        "name": "C#",
        "file_extensions": [".cs"],
        "run_command": "dotnet run",
        "test_command": "dotnet test",
        "package_manager": "dotnet",
        "notes": "Requires the .NET SDK and a project or solution file.",
    },
    "Go": {
        "name": "Go",
        "file_extensions": [".go"],
        "run_command": "go run <file.go>",
        "test_command": "go test ./...",
        "package_manager": "go modules",
        "notes": "Requires the Go toolchain; module-aware commands need go.mod.",
    },
    "Rust": {
        "name": "Rust",
        "file_extensions": [".rs"],
        "run_command": "cargo run",
        "test_command": "cargo test",
        "package_manager": "Cargo",
        "notes": "Requires Rust/Cargo and a Cargo.toml project manifest.",
    },
    "Swift": {
        "name": "Swift",
        "file_extensions": [".swift"],
        "run_command": "swift run",
        "test_command": "swift test",
        "package_manager": "Swift Package Manager",
        "notes": "Requires Swift; package commands need Package.swift.",
    },
    "SQL": {
        "name": "SQL",
        "file_extensions": [".sql"],
        "run_command": "Use a database-specific client such as sqlite3, psql, or mysql.",
        "test_command": "Database- and project-specific; no universal SQL test command.",
        "package_manager": "Database-specific",
        "notes": "Requires a matching database and client; SQL dialects differ.",
    },
    "Bash": {
        "name": "Bash",
        "file_extensions": [".sh", ".bash"],
        "run_command": "bash <file.sh>",
        "test_command": "shellcheck <file.sh> or bash -n <file.sh>",
        "package_manager": "OS package manager (if needed)",
        "notes": "Requires Bash; ShellCheck is optional for static analysis.",
    },
}

_EXTENSION_LANGUAGE = {
    extension: language
    for language, rules in LANGUAGE_RULES.items()
    for extension in rules["file_extensions"]
}
_SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "virtualenv",
    "node_modules",
    "__pycache__",
}


def get_language_rules(language: str) -> dict[str, Any] | str:
    """Return the rules for a language name, case-insensitively."""
    if not isinstance(language, str):
        return "Error: language must be a string."
    for name, rules in LANGUAGE_RULES.items():
        if name.lower() == language.strip().lower():
            return rules
    aliases = {"bash / shell": "Bash", "csharp": "C#", "typescript": "TypeScript"}
    alias_target = aliases.get(language.strip().lower())
    if alias_target:
        return LANGUAGE_RULES[alias_target]
    return f"Unknown language: {language}. Supported languages: {', '.join(LANGUAGE_RULES)}."


def _language_for_file(path: Path) -> str | None:
    return _EXTENSION_LANGUAGE.get(path.suffix.lower())


def project_language_counts(root: Path) -> dict[str, int]:
    """Count supported source files below a project directory."""
    counts: dict[str, int] = {}
    for current, directories, filenames in os.walk(root):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in _SKIP_DIRECTORIES
            and not (Path(current) / directory / "pyvenv.cfg").is_file()
        )
        for filename in filenames:
            language = _language_for_file(Path(filename))
            if language:
                counts[language] = counts.get(language, 0) + 1
    return counts


def project_languages(path: str = ".") -> list[str]:
    """Return all supported languages found in a project directory."""
    root = Path(path)
    if root.is_absolute() or ".." in root.parts:
        return []
    try:
        resolved = root.resolve()
        if not resolved.is_relative_to(Path.cwd().resolve()) or not resolved.is_dir():
            return []
    except (OSError, RuntimeError, ValueError):
        return []
    counts = project_language_counts(resolved)
    return sorted(counts, key=lambda language: (-counts[language], language))


def detect_language(path: str) -> str:
    """Detect a supported language from a file extension or project directory."""
    if not isinstance(path, str):
        return "Error: path must be a string."
    target = Path(path)
    if target.is_absolute() or ".." in target.parts:
        return f"Error: path is outside the project: {path}"

    try:
        resolved = target.resolve()
        if not resolved.is_relative_to(Path.cwd().resolve()):
            return f"Error: path is outside the project: {path}"
    except (OSError, RuntimeError, ValueError):
        return f"Error: cannot resolve path: {path}"

    if resolved.is_file():
        language = _language_for_file(resolved)
        return language or f"Unknown language for file extension: {resolved.suffix or '(none)'}"
    if not resolved.exists() and resolved.suffix:
        language = _language_for_file(resolved)
        if language:
            return language
    if not resolved.is_dir():
        return f"Error: path does not exist: {path}"

    counts = project_language_counts(resolved)
    if not counts:
        return "No supported language files found."
    languages = sorted(counts, key=lambda language: (-counts[language], language))
    if len(languages) == 1:
        return languages[0]
    return (
        "Multiple languages detected: "
        + ", ".join(f"{language} ({counts[language]} files)" for language in languages)
        + ". Ask which language to work on if the request does not make it clear."
    )
