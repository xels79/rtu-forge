"""Full-screen prompt-toolkit UI that preserves the command buffer."""

from __future__ import annotations

from io import StringIO
import threading
from collections.abc import Callable

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from rich.console import Console

from .bionic_cli import BionicContext, execute_command
from .bionic_completion import BionicCompleter
from .bionic_render import render_view


def run_tui(ctx: BionicContext, reconnect: Callable[[], None]) -> None:
    previous_view = ["main"]
    status = ["F2 настройки · Esc назад · F5 применить · Ctrl+S сохранить"]

    def screen_text() -> ANSI:
        stream = StringIO()
        console = Console(file=stream, width=120, force_terminal=True, color_system="standard")
        console.print(render_view(ctx.view, ctx.model, ctx.journal, ctx.settings, ctx.draft, prompt=False))
        return ANSI(stream.getvalue())

    body = FormattedTextControl(screen_text, focusable=False)
    command = TextArea(
        height=1, prompt="bionic-immitator> ", multiline=False, wrap_lines=False,
        completer=BionicCompleter(test_mode=ctx.test_mode), complete_while_typing=False,
    )
    footer = FormattedTextControl(lambda: FormattedText([("class:status", status[0])]))
    bindings = KeyBindings()
    app: Application[None]

    def run_line(line: str) -> None:
        try:
            result = execute_command(ctx, line)
            status[0] = "Готово"
            if result == "reconnect":
                reconnect()
            elif result == "exit":
                app.exit()
        except (ValueError, RuntimeError) as exc:
            status[0] = f"Ошибка: {exc}"
        app.invalidate()

    @bindings.add("enter")
    def _enter(event) -> None:
        line = command.text
        command.buffer.document = command.buffer.document.__class__("", 0)
        run_line(line)

    @bindings.add("f2")
    def _settings(event) -> None:
        if ctx.view != "settings":
            previous_view[0] = ctx.view
        ctx.view = "settings"
        app.invalidate()

    @bindings.add("escape")
    def _back(event) -> None:
        ctx.view, previous_view[0] = previous_view[0], ctx.view
        app.invalidate()

    @bindings.add("f5")
    def _apply(event) -> None:
        run_line("settings apply")

    @bindings.add("c-s")
    def _save(event) -> None:
        run_line("settings save")

    @bindings.add("c-c")
    @bindings.add("c-d")
    def _exit(event) -> None:
        app.exit()

    root = HSplit([
        Window(body, always_hide_cursor=True),
        Window(height=1, content=footer),
        command,
    ])
    app = Application(layout=Layout(root, focused_element=command), key_bindings=bindings, full_screen=True, mouse_support=False)
    stop = threading.Event()

    def refresh() -> None:
        while not stop.wait(ctx.settings.ui_interval_ms / 1000.0):
            app.invalidate()

    thread = threading.Thread(target=refresh, name="bionic-ui-refresh", daemon=True)
    thread.start()
    try:
        app.run()
    finally:
        stop.set()
        thread.join(timeout=1)
