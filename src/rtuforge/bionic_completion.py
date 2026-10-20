"""Context-aware completion for the Bionic Immitator command line."""

from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion

from .bionic_config import OPTION_SPECS


COMMANDS = sorted({
    "alarm", "devices", "exit", "fault", "help", "irrigation", "log",
    "pipe", "ports", "pressure", "pump", "quit", "relay", "sensor",
    "settings", "sim", "status", "tank", "view",
})


def completion_candidates(text: str, *, test_mode: bool = False) -> list[str]:
    trailing = text.endswith(" ")
    parts = text.casefold().split()
    prefix = "" if trailing else (parts[-1] if parts else "")
    completed = parts if trailing else parts[:-1]
    if not completed:
        candidates = COMMANDS if test_mode else [item for item in COMMANDS if item != "relay"]
    elif completed == ["view"]:
        candidates = ["main", "settings", "log", "rs485", "tanks", "pumps", "pressure", "irrigation", "light", "sensors"]
    elif completed == ["tank"]:
        candidates = ["list", "bo", "bp", "bso1", "bso2"]
    elif completed == ["pump"]:
        candidates = ["list", "bo-to-bp", "bso1-to-bp", "bso2-to-bp"]
    elif completed == ["sensor"]:
        candidates = ["list", "bo-min", "bo-max", "bp-min", "bp-max", "bso1-min", "bso1-max", "bso2-min", "bso2-max"]
    elif completed == ["fault"]:
        candidates = ["list", "clear", "leak", "blockage"]
    elif completed == ["alarm"]:
        candidates = ["list", "reset"]
    elif completed == ["sim"]:
        candidates = ["start", "pause", "resume", "speed", "reset"]
    elif completed == ["settings"]:
        candidates = ["list", "set", "apply", "save"]
    elif completed == ["settings", "set"]:
        candidates = sorted(OPTION_SPECS)
    elif completed == ["log"]:
        candidates = ["last", "filter", "export"]
    elif completed == ["log", "filter"]:
        candidates = ["alarms", "rs485", "tanks", "pumps", "all"]
    elif completed and completed[-1] in {"leak", "blockage", "force"}:
        candidates = ["on", "off"]
    else:
        candidates = []
    return sorted(candidate for candidate in candidates if candidate.startswith(prefix))


class BionicCompleter(Completer):
    def __init__(self, *, test_mode: bool = False) -> None:
        self.test_mode = test_mode

    def get_completions(self, document, complete_event):
        prefix = document.get_word_before_cursor()
        for candidate in completion_candidates(document.text_before_cursor, test_mode=self.test_mode):
            yield Completion(candidate, start_position=-len(prefix))
