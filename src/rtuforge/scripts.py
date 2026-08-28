from __future__ import annotations

import configparser
from collections.abc import Mapping, Sequence
from pathlib import Path


def validate_script_name(name: str) -> None:
    if not name.strip():
        raise ValueError("Script name must not be empty.")
    if any(character in name for character in "\r\n=:"):
        raise ValueError("Script name must not contain CR, LF, '=' or ':'.")


class ScriptStore:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        if self.path.exists():
            parser.read(self.path, encoding="utf-8")
        if not parser.has_section("scripts"):
            parser.add_section("scripts")
        return parser

    def list(self) -> list[str]:
        parser = self._load()
        return sorted(parser["scripts"].keys(), key=str.lower)

    def get(self, name: str) -> list[str]:
        parser = self._load()
        if name not in parser["scripts"]:
            raise KeyError(name)
        value = parser["scripts"][name]
        return [line.strip() for line in value.splitlines() if line.strip()]

    def set(self, name: str, lines: list[str]) -> None:
        validate_script_name(name)
        parser = self._load()
        parser["scripts"][name] = "\n" + "\n".join(f"    {line}" for line in lines)
        with self.path.open("w", encoding="utf-8") as stream:
            parser.write(stream)

    def set_many(
        self,
        scripts: Mapping[str, Sequence[str]],
        *,
        overwrite: bool = False,
    ) -> None:
        for name in scripts:
            validate_script_name(name)
        parser = self._load()
        conflicts = [name for name in scripts if name in parser["scripts"]]
        if conflicts and not overwrite:
            raise FileExistsError(", ".join(sorted(conflicts, key=str.lower)))
        for name, lines in scripts.items():
            parser["scripts"][name] = "\n" + "\n".join(f"    {line}" for line in lines)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as stream:
            parser.write(stream)

    def delete(self, name: str) -> None:
        parser = self._load()
        if name not in parser["scripts"]:
            raise KeyError(name)
        del parser["scripts"][name]
        with self.path.open("w", encoding="utf-8") as stream:
            parser.write(stream)
