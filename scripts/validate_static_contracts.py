from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_TARGETS = [ROOT / "main.py", ROOT / "config.py", ROOT / "database.py", ROOT / "utils.py", ROOT / "cogs"]
TEXT_TARGETS = [ROOT / "main.py", ROOT / "config.py", ROOT / "database.py", ROOT / "utils.py", ROOT / "cogs", ROOT / ".github"]

EMBED_TITLE_LIMIT = 256
EMBED_DESCRIPTION_LIMIT = 4096
EMBED_FIELD_NAME_LIMIT = 256
EMBED_FIELD_VALUE_LIMIT = 1024
SELECT_OPTIONS_LIMIT = 25

SECRET_PATTERNS = [
    re.compile(r"(discord|bot)[_-]?token\s*=\s*['\"][^'\"]{20,}['\"]", re.IGNORECASE),
    re.compile(r"mongodb(?:\\+srv)?://[^\\s'\"]+", re.IGNORECASE),
    re.compile(r"Bearer\s+[-A-Za-z0-9_.]{20,}", re.IGNORECASE),
]


def iter_files(paths: list[Path], suffixes: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix in suffixes:
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in path.rglob("*") if p.is_file() and p.suffix in suffixes)
    return sorted(files)


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                parts.append("{}")
            else:
                return None
        return "".join(parts)
    return None


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        names = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            names.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            names.append(value.id)
        return ".".join(reversed(names))
    if isinstance(func, ast.Name):
        return func.id
    return ""


def keyword_value(node: ast.Call, name: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def validate_embed_limits(file: Path, errors: list[str]) -> None:
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        name = call_name(node)
        if name.endswith("discord.Embed") or name == "Embed":
            title = literal_string(keyword_value(node, "title"))
            description = literal_string(keyword_value(node, "description"))
            if title and len(title) > EMBED_TITLE_LIMIT:
                errors.append(f"{file}: embed title literal exceeds {EMBED_TITLE_LIMIT} chars")
            if description and len(description) > EMBED_DESCRIPTION_LIMIT:
                errors.append(f"{file}: embed description literal exceeds {EMBED_DESCRIPTION_LIMIT} chars")

        if name.endswith("add_field"):
            field_name = literal_string(keyword_value(node, "name"))
            field_value = literal_string(keyword_value(node, "value"))
            if field_name and len(field_name) > EMBED_FIELD_NAME_LIMIT:
                errors.append(f"{file}: embed field name literal exceeds {EMBED_FIELD_NAME_LIMIT} chars")
            if field_value and len(field_value) > EMBED_FIELD_VALUE_LIMIT:
                errors.append(f"{file}: embed field value literal exceeds {EMBED_FIELD_VALUE_LIMIT} chars")

        if name.endswith("ui.Select") or name.endswith("discord.ui.Select"):
            options = keyword_value(node, "options")
            if isinstance(options, ast.List) and len(options.elts) > SELECT_OPTIONS_LIMIT:
                errors.append(f"{file}: select menu literal exceeds {SELECT_OPTIONS_LIMIT} options")


def validate_secret_literals(file: Path, errors: list[str]) -> None:
    text = file.read_text(encoding="utf-8", errors="ignore")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            errors.append(f"{file}: possible committed secret literal")


def main() -> int:
    errors: list[str] = []
    for file in iter_files(PYTHON_TARGETS, (".py",)):
        validate_embed_limits(file, errors)
    for file in iter_files(TEXT_TARGETS, (".py", ".yml", ".yaml", ".md", ".txt", ".toml", ".json")):
        validate_secret_literals(file, errors)

    if errors:
        print("Static contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Static contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
