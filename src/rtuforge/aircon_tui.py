"""Full-screen prompt-toolkit user interface with exactly two console rows."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
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


class CommandQueue:
    """Run submitted command lines in strict FIFO order on one worker."""

    _STOP = object()

    def __init__(
        self,
        handler: Callable[[str], None],
        error_handler: Callable[[Exception], None] | None = None,
    ) -> None:
        self.handler = handler
        self.error_handler = error_handler
        self.items: queue.Queue[str | object] = queue.Queue()
        self.thread = threading.Thread(
            target=self._run, name="aircon-command", daemon=True
        )
        self.started = False
        self.closed = False
        self.lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self.lifecycle_lock:
            if self.started:
                return
            if self.closed:
                raise RuntimeError("очередь команд уже закрыта")
            self.started = True
            self.thread.start()

    def submit(self, line: str) -> None:
        with self.lifecycle_lock:
            if not self.started or self.closed:
                raise RuntimeError("очередь команд не запущена")
            self.items.put(line)

    def wait_idle(self) -> None:
        self.items.join()

    def stop(self, *, cancel_pending: bool = False) -> None:
        with self.lifecycle_lock:
            if self.closed:
                return
            self.closed = True
            if cancel_pending:
                while True:
                    try:
                        self.items.get_nowait()
                    except queue.Empty:
                        break
                    else:
                        self.items.task_done()
            if self.started:
                self.items.put(self._STOP)
        if self.started:
            self.thread.join()

    def _run(self) -> None:
        while True:
            item = self.items.get()
            try:
                if item is self._STOP:
                    return
                try:
                    self.handler(str(item))
                except Exception as exc:
                    if self.error_handler is not None:
                        self.error_handler(exc)
            finally:
                self.items.task_done()


def remember_command(buffer: Buffer, line: str) -> None:
    """Persist an accepted line before resetting the prompt buffer."""
    buffer.text = line
    buffer.append_to_history()
    buffer.reset()


def build_tui(
    ctx: AirconContext, *, input: object | None = None, output: object | None = None
) -> tuple[Application[None], Poller, CommandQueue]:
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

    def queue_error(exc: Exception) -> None:
        ctx.notice = f"Ошибка: {exc}"
        app.invalidate()

    command_queue = CommandQueue(run_line, queue_error)

    @bindings.add("enter")
    def _enter(event) -> None:
        line = command.text.strip()
        if not line:
            command.text = ""
            return
        remember_command(command.buffer, line)
        command_queue.submit(line)

    @bindings.add("f1")
    def _help(event) -> None:
        switch("help")

    @bindings.add("f2")
    def _status(event) -> None:
        if ctx.transport.connected:
            command_queue.submit("status")
        else:
            switch("status")

    @bindings.add("f3")
    def _ports(event) -> None:
        command_queue.submit("ports")

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
    return app, poller, command_queue


def run_tui(ctx: AirconContext) -> None:
    app, poller, command_queue = build_tui(ctx)
    command_queue.start()
    poller_started = False
    try:
        poller.start()
        poller_started = True
        app.run()
    finally:
        command_queue.stop(cancel_pending=True)
        if poller_started:
            poller.stop()
