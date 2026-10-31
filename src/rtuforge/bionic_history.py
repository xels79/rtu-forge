"""Small persistent command history used by the full-screen console."""

from __future__ import annotations

from pathlib import Path


class CommandHistory:
    """Keep a bounded, de-duplicated UTF-8 command history."""

    def __init__(self, path: Path, *, limit: int = 500) -> None:
        if not 200 <= limit <= 1000:
            raise ValueError("Размер истории должен быть в диапазоне 200..1000")
        self.path = path
        self.limit = limit
        self.entries = self._load()

    def _load(self) -> list[str]:
        if not self.path.exists():
            return []
        result: list[str] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            command = raw.strip()
            if command and (not result or result[-1] != command):
                result.append(command)
        return result[-self.limit :]

    def append(self, command: str) -> None:
        command = command.strip()
        if not command or self.entries and self.entries[-1] == command:
            return
        self.entries.append(command)
        self.entries = self.entries[-self.limit :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(self.entries) + "\n", encoding="utf-8")
