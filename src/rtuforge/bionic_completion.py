"""Context-aware completion for the Bionic Immitator command line."""

from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion

from .bionic_config import OPTION_SPECS
from .bionic_render import VIEW_NAMES


COMMANDS = sorted({
    "alarm", "devices", "exit", "fault", "help", "irrigation", "log",
    "pipe", "ponics", "ports", "pressure", "pump", "quit", "relay", "sensor",
    "settings", "sim", "status", "tank", "view",
})

TANKS = ["bo", "bp", "bso1", "bso2"]
PUMPS = ["bo-to-bp", "bso1-to-bp", "bso2-to-bp"]
SENSORS = [f"{tank}-{kind}" for tank in TANKS for kind in ("min", "max")]
DEVICES = ["relay-32ch", "ao-1", "ao-2", "ao-3", "ponics", "ai-pressure", "hp1", "hp2", "sensor-relay"]


def completion_candidates(text: str, *, test_mode: bool = False) -> list[str]:
    trailing = text.endswith(" ")
    parts = text.casefold().split()
    prefix = "" if trailing else (parts[-1] if parts else "")
    completed = parts if trailing else parts[:-1]
    if not completed:
        candidates = COMMANDS if test_mode else [item for item in COMMANDS if item != "relay"]
    elif completed == ["view"]:
        candidates = [*VIEW_NAMES, "main", "drive"]
    elif completed == ["view", "ponics"]:
        candidates = ["settings", "registers"]
    elif completed == ["view", "drive"]:
        candidates = ["hp1", "hp2"]
    elif completed == ["help"]:
        candidates = ["search"]
    elif completed == ["devices"]:
        candidates = DEVICES
    elif completed == ["tank"]:
        candidates = ["list", *TANKS]
    elif len(completed) == 2 and completed[0] == "tank" and completed[1] in TANKS:
        candidates = ["level", "capacity"] + (["fill-rate"] if completed[1] == "bo" else [])
    elif completed == ["pump"]:
        candidates = ["list", *PUMPS]
    elif len(completed) == 2 and completed[0] == "pump" and completed[1] in PUMPS:
        candidates = ["flow"]
    elif completed == ["sensor"]:
        candidates = ["list", *SENSORS]
    elif len(completed) == 2 and completed[0] == "sensor" and completed[1] in SENSORS:
        candidates = ["threshold", "force", "auto"]
    elif len(completed) == 3 and completed[0] == "sensor" and completed[2] == "force":
        candidates = ["on", "off"]
    elif completed == ["pressure"]:
        candidates = ["target", "range", "rise-time", "fall-time"]
    elif completed == ["pipe"]:
        candidates = ["status", "repair", "rupture-threshold"]
    elif completed == ["irrigation"]:
        candidates = ["shelf"]
    elif completed == ["irrigation", "shelf"]:
        candidates = ["1", "2"]
    elif len(completed) == 3 and completed[:2] == ["irrigation", "shelf"]:
        candidates = ["flow-per-tier"]
    elif completed == ["fault"]:
        candidates = ["list", "clear", "leak", "blockage"]
    elif completed == ["fault", "clear"]:
        candidates = ["all"]
    elif completed in (["fault", "leak"], ["fault", "blockage"]):
        candidates = ["on", "off", "rate" if completed[-1] == "leak" else "severity"]
    elif completed == ["alarm"]:
        candidates = ["list", "reset"]
    elif completed == ["alarm", "reset"]:
        candidates = ["all"]
    elif completed == ["sim"]:
        candidates = ["start", "pause", "resume", "speed", "reset"]
    elif completed == ["sim", "reset"]:
        candidates = ["--confirm"]
    elif completed == ["settings"]:
        candidates = ["list", "set", "apply", "save"]
    elif completed == ["settings", "set"]:
        candidates = sorted(OPTION_SPECS)
    elif completed == ["ponics"]:
        candidates = ["dose", "set", "fault"]
    elif completed == ["ponics", "dose"]:
        candidates = ["a", "b", "c", "ph_plus", "ph_minus"]
    elif completed == ["ponics", "fault"]:
        candidates = ["offline", "ph", "ec", "temperature", "a", "b", "c", "ph_plus", "ph_minus"]
    elif len(completed) == 3 and completed[:2] == ["ponics", "fault"]:
        candidates = ["on", "off"]
    elif completed == ["log"]:
        candidates = ["last", "filter", "export"]
    elif completed == ["log", "filter"]:
        candidates = ["alarms", "rs485", "tanks", "pumps", "all"]
    elif completed == ["relay"] and test_mode:
        candidates = ["force"]
    elif completed == ["relay", "force"] and test_mode:
        candidates = [str(channel) for channel in range(1, 33)]
    elif len(completed) == 3 and completed[:2] == ["relay", "force"] and test_mode:
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
