from __future__ import annotations

from collections.abc import Iterable, Iterator

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

from .config import OPTION_SPECS, option_spec
from .i18n import help_topics
from .scripts import ScriptStore


TOP_LEVEL_COMMANDS: tuple[str, ...] = (
    "connect", "disconnect", "ports", "status", "send", "add", "run",
    "scripts", "ls", "list", "show", "delete", "options", "set", "pause",
    "history", "clear", "cls", "help", "exit", "quit",
)


def completion_candidates(
    text: str,
    script_names: Iterable[str] = (),
    sections: Iterable[str] = ("connection", "runtime", "history", "ui"),
) -> list[str]:
    trailing_space = bool(text) and text[-1].isspace()
    words = text.lower().split()
    fragment = "" if trailing_space else (words[-1] if words else "")
    completed = words if trailing_space else words[:-1]

    choices: Iterable[str]
    if completed in (["run"], ["show"], ["delete"], ["add"]):
        choices = ("script",)
    elif len(completed) == 2 and completed[0] in {"run", "show", "delete"} and completed[1] == "script":
        choices = script_names
    elif completed == ["set"]:
        choices = ("options",)
    elif completed == ["set", "options"]:
        choices = (spec.name for spec in OPTION_SPECS)
    elif len(completed) == 3 and completed[:2] == ["set", "options"]:
        try:
            choices = option_spec(completed[2]).choices
        except KeyError:
            choices = ()
    elif completed == ["options"]:
        choices = sections
    elif completed == ["help"]:
        choices = help_topics()
    elif completed == ["history"]:
        choices = ("clear",)
    elif completed == ["send"]:
        choices = ("--decode", "--raw", "-d", "-r")
    elif not completed:
        choices = TOP_LEVEL_COMMANDS
    else:
        choices = ()
    return sorted((choice for choice in choices if choice.lower().startswith(fragment)), key=str.lower)


class RTUForgeCompleter(Completer):
    def __init__(self, scripts: ScriptStore, sections: Iterable[str]):
        self.scripts = scripts
        self.sections = tuple(sections)

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        fragment = "" if not text or text[-1].isspace() else text.split()[-1]
        for candidate in completion_candidates(text, self.scripts.list(), self.sections):
            yield Completion(candidate, start_position=-len(fragment))
