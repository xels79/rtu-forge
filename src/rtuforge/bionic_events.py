"""Bounded persistent event journal for Bionic Immitator."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Event:
    at: str
    kind: str
    subject: str
    message: str
    previous: str | None = None
    current: str | None = None


class EventJournal:
    def __init__(self, path: Path, retention_days: int = 7, max_memory: int = 5000) -> None:
        self.path = path
        self.retention_days = retention_days
        self.max_memory = max_memory
        self.events: list[Event] = []
        self._load()

    def _cutoff(self) -> datetime:
        return datetime.now().astimezone() - timedelta(days=self.retention_days)

    @staticmethod
    def _local_datetime(value: str) -> datetime:
        """Convert stored UTC/offset timestamps to the computer's local zone."""
        return datetime.fromisoformat(value).astimezone()

    def _load(self) -> None:
        if not self.path.exists():
            return
        cutoff = self._cutoff()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                stored = Event(**json.loads(line))
                local_at = self._local_datetime(stored.at)
                if local_at >= cutoff:
                    self.events.append(Event(
                        local_at.isoformat(), stored.kind, stored.subject,
                        stored.message, stored.previous, stored.current,
                    ))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        self.events = self.events[-self.max_memory :]

    def add(
        self, kind: str, subject: str, message: str,
        previous: str | None = None, current: str | None = None,
    ) -> Event:
        event = Event(
            datetime.now().astimezone().isoformat(), kind, subject, message,
            previous, current,
        )
        self.events.append(event)
        self.events = self.events[-self.max_memory :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        return event

    def filtered(self, category: str = "all", limit: int | None = None) -> list[Event]:
        aliases = {
            "alarms": "АВАРИЯ", "rs485": "RS485", "tanks": "БАК",
            "pumps": "НАСОС", "ponics": "PONICS",
        }
        events: Iterable[Event] = self.events
        if category != "all":
            wanted = aliases.get(category, category).casefold()
            events = (event for event in events if event.kind.casefold() == wanted)
        result = list(events)
        return result[-limit:] if limit is not None else result

    def export_csv(self, path: Path, events: Iterable[Event] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=Event.__dataclass_fields__)
            writer.writeheader()
            for event in events if events is not None else self.events:
                writer.writerow(asdict(event))

    def compact(self) -> None:
        cutoff = self._cutoff()
        self.events = [e for e in self.events if self._local_datetime(e.at) >= cutoff]
        self.events = self.events[-self.max_memory :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = "".join(json.dumps(asdict(e), ensure_ascii=False) + "\n" for e in self.events)
        self.path.write_text(content, encoding="utf-8")
