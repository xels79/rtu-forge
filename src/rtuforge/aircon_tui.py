"""Full-screen prompt-toolkit user interface with exactly two console rows."""

from __future__ import annotations

import threading

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from .aircon_cli import AirconContext, Poller, execute_command
from .aircon_render import render_help_lines, render_ports_lines, render_settings_lines, render_status_lines


COMMANDS = [
    "on", "off", "status", "temp", "mode cool", "mode heat", "mode auto",
    "mode dry", "mode fan", "fan auto", "fan 1", "fan 2", "fan 3", "ports",
    "connect", "disconnect", "settings", "help", "set", "exit",
]


def build_tui(
    ctx: AirconContext, *, input: object | None = None, output: object | None = None
) -> tuple[Application[None], Poller]:
    """Build the application; the last two layout rows are status and input."""
    app: Application[None]

    def dimensions() -> tuple[int, int]:
        size = get_app().output.get_size()
        return max(20, size.columns), max(1, size.rows - 2)

    def screen_text() -> FormattedText:
        width, height = dimensions()
        if ctx.view == "help":
            lines = render_help_lines(width=width, height=height)
        elif ctx.view == "settings":
            lines = render_settings_lines(ctx.settings, width=width, height=height)
        elif ctx.view == "ports":
            lines = render_ports_lines(ctx.ports or [], width=width, height=height)
        else:
            lines = render_status_lines(ctx.state, ctx.settings, width=width, height=height)
        fragments: list[tuple[str, str]] = []
        for index, line in enumerate(lines):
            style = ""
            if "НЕТ СВЯЗИ" in line or "ОШИБ" in line:
                style = "class:error"
            elif "НА СВЯЗИ" in line or "Показания обновлены" in line:
                style = "class:ok"
            elif index == 0 or line.startswith("──"):
                style = "class:title"
            fragments.append((style, line + ("\n" if index < len(lines) - 1 else "")))
        return FormattedText(fragments)

    body = FormattedTextControl(screen_text, focusable=False)
    footer = FormattedTextControl(lambda: FormattedText([("class:footer", ctx.notice)]))
    command = TextArea(
        height=1, prompt="aircon> ", multiline=False, wrap_lines=False,
        completer=WordCompleter(COMMANDS, sentence=True), complete_while_typing=False,
        history=FileHistory(str(ctx.home / ".aircon_history")),
    )
    bindings = KeyBindings()

    def switch(view: str) -> None:
        ctx.show(view)
        app.invalidate()

    def run_line(line: str) -> None:
        try:
            result = execute_command(ctx, line)
            if result == "exit":
                app.exit()
        except (ValueError, RuntimeError, OSError) as exc:
            ctx.notice = f"Ошибка: {exc}"
        app.invalidate()

    @bindings.add("enter")
    def _enter(event) -> None:
        line = command.text.strip()
        command.text = ""
        if not line:
            return
        if line.casefold() in {"exit", "quit"}:
            app.exit()
            return
        threading.Thread(target=run_line, args=(line,), name="aircon-command", daemon=True).start()

    @bindings.add("f1")
    def _help(event) -> None:
        switch("help")

    @bindings.add("f2")
    def _status(event) -> None:
        if ctx.transport.connected:
            threading.Thread(target=run_line, args=("status",), daemon=True).start()
        else:
            switch("status")

    @bindings.add("f3")
    def _ports(event) -> None:
        threading.Thread(target=run_line, args=("ports",), daemon=True).start()

    @bindings.add("f4")
    def _settings(event) -> None:
        switch("settings")

    @bindings.add("escape")
    def _back(event) -> None:
        ctx.view, ctx.previous_view = ctx.previous_view, ctx.view
        app.invalidate()

    @bindings.add("c-c")
    @bindings.add("c-d")
    def _exit(event) -> None:
        app.exit()

    root = HSplit([
        Window(body, always_hide_cursor=True, wrap_lines=False),
        Window(height=1, content=footer),
        command,
    ])
    app = Application(
        layout=Layout(root, focused_element=command), key_bindings=bindings,
        full_screen=True, input=input, output=output,
        style=Style.from_dict({
            "title": "bold #5fd7ff", "ok": "bold #00aa00", "error": "bold #ff0000",
            "footer": "bg:#444444 #ffffff",
        }),
    )
    poller = Poller(ctx, app.invalidate)
    return app, poller


def run_tui(ctx: AirconContext) -> None:
    app, poller = build_tui(ctx)
    poller.start()
    try:
        app.run()
    finally:
        poller.stop()
