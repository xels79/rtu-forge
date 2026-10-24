from __future__ import annotations

from collections.abc import Iterable, Iterator

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

from .stand_protocol import OUTPUT_CHANNEL_NAMES, OUTPUT_RANGES, RELAY_CHANNEL_COUNT


TOP_LEVEL_COMMANDS = (
    "tank",
    "on",
    "off",
    "of",
    "output",
    "reset",
    "connect",
    "disconnect",
    "ports",
    "status",
    "paths",
    "set",
    "help",
    "clear",
    "cls",
    "exit",
    "quit",
)


def completion_candidates(text: str) -> list[str]:
    trailing_space = bool(text) and text[-1].isspace()
    words = text.lower().split()
    fragment = "" if trailing_space else (words[-1] if words else "")
    completed = words if trailing_space else words[:-1]

    choices: Iterable[str]
    if not completed:
        choices = TOP_LEVEL_COMMANDS
    elif completed == ["tank"]:
        choices = ("1", "2", "3", "4")
    elif len(completed) == 2 and completed[0] == "tank":
        choices = ("empty", "middle", "full")
    elif completed[0] in {"on", "off", "of"}:
        choices = (str(channel) for channel in range(1, RELAY_CHANNEL_COUNT + 1) if str(channel) not in completed[1:])
    elif completed == ["output"]:
        choices = OUTPUT_CHANNEL_NAMES
    elif completed == ["set"]:
        choices = ("relay-id", "output-id", "output-range")
    elif completed == ["set", "output-range"]:
        choices = OUTPUT_RANGES
    elif completed == ["reset"]:
        choices = ("all",)
    elif completed == ["help"]:
        choices = ("tank", "on", "off", "of", "output", "reset", "set", "status", "connect", "ports")
    else:
        choices = ()
    return sorted(
        (item for item in choices if item.lower().startswith(fragment)), key=str.lower
    )


class StandForgeCompleter(Completer):
    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        fragment = "" if not text or text[-1].isspace() else text.split()[-1]
        for candidate in completion_candidates(text):
            yield Completion(candidate, start_position=-len(fragment))
