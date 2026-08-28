from __future__ import annotations

import configparser
from collections.abc import Mapping, Sequence
from pathlib import Path

from .scripts import validate_script_name


SCRIPT_FILE_FORMAT = "scripts-v1"


def resolve_script_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved.resolve()


def load_script_file(path: str | Path) -> dict[str, list[str]]:
    resolved = resolve_script_path(path)
    parser = configparser.ConfigParser(interpolation=None, strict=True, delimiters=("=",))
    parser.optionxform = str
    try:
        with resolved.open("r", encoding="utf-8-sig") as stream:
            parser.read_file(stream)
    except UnicodeDecodeError as exc:
        raise ValueError(f"Script file is not valid UTF-8: {resolved}") from exc
    except configparser.Error as exc:
        raise ValueError(f"Invalid script file: {exc}") from exc

    if not parser.has_section("rtuforge"):
        raise ValueError("Script file is missing [rtuforge].")
    if not parser.has_option("rtuforge", "format"):
        raise ValueError("Script file is missing rtuforge.format.")
    value = parser.get("rtuforge", "format").strip()
    if value != SCRIPT_FILE_FORMAT:
        raise ValueError(f"Unsupported script file format: {value}")
    if not parser.has_section("scripts"):
        raise ValueError("Script file is missing [scripts].")

    scripts: dict[str, list[str]] = {}
    for name, value in parser.items("scripts", raw=True):
        validate_script_name(name)
        scripts[name] = [line.strip() for line in value.splitlines() if line.strip()]
    return scripts


def save_script_file(
    path: str | Path,
    scripts: Mapping[str, Sequence[str]],
    *,
    overwrite: bool = False,
) -> Path:
    resolved = resolve_script_path(path)
    if resolved.exists() and not overwrite:
        raise FileExistsError(resolved)

    parser = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    parser.optionxform = str
    parser.add_section("rtuforge")
    parser["rtuforge"]["format"] = SCRIPT_FILE_FORMAT
    parser.add_section("scripts")
    for name, lines in scripts.items():
        validate_script_name(name)
        parser["scripts"][name] = "\n" + "\n".join(f"    {line}" for line in lines)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# RTU Forge script file\n\n")
        parser.write(stream)
    return resolved
