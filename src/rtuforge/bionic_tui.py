"""Fixed full-screen prompt-toolkit interface for Bionic Immitator."""

from __future__ import annotations

import threading
from collections.abc import Callable

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from .bionic_cli import BionicContext, execute_command
from .bionic_completion import BionicCompleter
from .bionic_history import CommandHistory
from .bionic_render import ScreenPage, render_page


def clamp_scroll(current: int, delta: int, total: int, height: int) -> int:
    """Move a viewport without allowing blank space past the last row."""
    return min(max(0, current + delta), max(0, total - max(1, height)))


def run_tui(ctx: BionicContext, reconnect: Callable[[], None]) -> None:
    previous_view = ["status"]
    status = ["F1 справка · F2 настройки · F3 статус · F4 устройства · F5 порты · F6 журнал"]
    scroll_offsets: dict[str, int] = {}
    selected_setting = ["sensor:bo-min"]
    history = CommandHistory(ctx.home / ".bionic-immitator-history")
    history_index = [len(history.entries)]
    history_scratch = [""]
    app: Application[None]

    def dimensions() -> tuple[int, int]:
        size = get_app().output.get_size()
        return max(20, size.columns), max(1, size.rows - 3)

    def current_page() -> tuple[ScreenPage, int, int]:
        width, height = dimensions()
        page = render_page(
            ctx.view, ctx.model, ctx.journal, ctx.settings, ctx.draft,
            ctx.saved or ctx.settings, width=width, log_filter=ctx.log_filter,
            help_query=ctx.help_query, relay_state=ctx.sensor_relay_state,
        )
        scroll = clamp_scroll(scroll_offsets.get(ctx.view, 0), 0, len(page.lines), height)
        scroll_offsets[ctx.view] = scroll
        return page, scroll, height

    def mouse_handler(absolute_row: int):
        def handle(mouse_event) -> None:
            page, scroll, height = current_page()
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                scroll_offsets[ctx.view] = clamp_scroll(scroll, -3, len(page.lines), height)
            elif mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                scroll_offsets[ctx.view] = clamp_scroll(scroll, 3, len(page.lines), height)
            elif mouse_event.event_type == MouseEventType.MOUSE_UP and ctx.view in {"settings", "sensors", "ponics-settings", "light-settings"}:
                if absolute_row < len(page.row_keys) and page.row_keys[absolute_row]:
                    selected_setting[0] = page.row_keys[absolute_row] or selected_setting[0]
            app.invalidate()
        return handle

    def screen_text() -> FormattedText:
        page, scroll, height = current_page()
        visible = page.lines[scroll : scroll + height]
        visible += [""] * (height - len(visible))
        fragments = [("class:title", f"BIONIC IMMITATOR — {page.simulation_status} | {page.title}\n")]
        for local_row, line in enumerate(visible):
            absolute_row = scroll + local_row
            selected = False
            if ctx.view in {"settings", "sensors", "ponics-settings", "light-settings"} and absolute_row < len(page.row_keys):
                if page.row_keys[absolute_row] == selected_setting[0]:
                    selected = True
            suffix = "\n" if local_row < height - 1 else ""
            line_fragments = (
                page.styled_lines[absolute_row]
                if page.styled_lines is not None and absolute_row < len(page.styled_lines)
                else (("", line),)
            )
            if not line_fragments:
                line_fragments = (("", ""),)
            for fragment_index, (semantic_style, text) in enumerate(line_fragments):
                style = "class:selected" if selected else (f"class:{semantic_style}" if semantic_style else "")
                tail = suffix if fragment_index == len(line_fragments) - 1 else ""
                fragments.append((style, text + tail, mouse_handler(absolute_row)))
        return FormattedText(fragments)

    body = FormattedTextControl(screen_text, focusable=False)
    command = TextArea(
        height=1, prompt="bionic-immitator> ", multiline=False, wrap_lines=False,
        completer=BionicCompleter(test_mode=ctx.test_mode), complete_while_typing=False,
    )
    footer = FormattedTextControl(
        lambda: FormattedText([("class:status", ctx.notice or status[0])])
    )
    bindings = KeyBindings()

    def set_command(text: str) -> None:
        command.buffer.document = Document(text, len(text))

    def switch_view(name: str) -> None:
        if ctx.view != name:
            previous_view[0] = ctx.view
        ctx.view = name
        ctx.notice = ""
        app.invalidate()

    def move_scroll(delta: int) -> None:
        page, scroll, height = current_page()
        scroll_offsets[ctx.view] = clamp_scroll(scroll, delta, len(page.lines), height)
        app.invalidate()

    def move_setting(delta: int) -> None:
        page, _, height = current_page()
        names = [name for name in page.row_keys if name]
        index = names.index(selected_setting[0]) if selected_setting[0] in names else (-1 if delta > 0 else len(names))
        selected_setting[0] = names[min(max(0, index + delta), len(names) - 1)]
        row = page.row_keys.index(selected_setting[0])
        current = scroll_offsets.get(ctx.view, 0)
        if row < current:
            scroll_offsets[ctx.view] = row
        elif row >= current + height:
            scroll_offsets[ctx.view] = row - height + 1
        app.invalidate()

    def run_line(line: str) -> None:
        history.append(line)
        history_index[0] = len(history.entries)
        history_scratch[0] = ""
        ctx.notice = ""
        try:
            old_view = ctx.view
            result = execute_command(ctx, line)
            if old_view != ctx.view:
                previous_view[0] = old_view
            status[0] = "Готово"
            if result == "reconnect":
                reconnect()
            elif result == "exit":
                app.exit()
        except (ValueError, RuntimeError) as exc:
            ctx.notice = f"Ошибка: {exc}"
        app.invalidate()

    @bindings.add("enter")
    def _enter(event) -> None:
        line = command.text.strip()
        if not line and ctx.view in {"settings", "sensors", "ponics-settings", "light-settings"}:
            if ctx.view == "light-settings":
                page, _, _ = current_page()
                light_keys = [key for key in page.row_keys if key and key.startswith("light:")]
                selected = selected_setting[0] if selected_setting[0] in light_keys else light_keys[0]
                selected_setting[0] = selected
                set_command(f"light set {selected.split(':',1)[1]} type ")
                return
            if selected_setting[0].startswith("sensor:"):
                sensor_id = selected_setting[0].split(":", 1)[1]
                set_command(f"sensor {sensor_id} threshold ")
            elif selected_setting[0].startswith("equipment:"):
                _, equipment_id, field_name = selected_setting[0].split(":", 2)
                set_command(f"equipment set {equipment_id} {field_name} ")
            else:
                set_command(f"settings set {selected_setting[0]} ")
            return
        set_command("")
        run_line(line)

    @bindings.add("up")
    def _history_up(event) -> None:
        if not history.entries:
            return
        if history_index[0] == len(history.entries):
            history_scratch[0] = command.text
        history_index[0] = max(0, history_index[0] - 1)
        set_command(history.entries[history_index[0]])

    @bindings.add("down")
    def _history_down(event) -> None:
        if history_index[0] >= len(history.entries):
            return
        history_index[0] += 1
        set_command(history.entries[history_index[0]] if history_index[0] < len(history.entries) else history_scratch[0])

    @bindings.add("pageup")
    def _page_up(event) -> None:
        _, _, height = current_page()
        move_scroll(-height)

    @bindings.add("pagedown")
    def _page_down(event) -> None:
        _, _, height = current_page()
        move_scroll(height)

    @bindings.add("escape", "k")
    def _setting_up(event) -> None:
        if ctx.view in {"settings", "sensors", "ponics-settings", "light-settings"}:
            move_setting(-1)

    @bindings.add("escape", "j")
    def _setting_down(event) -> None:
        if ctx.view in {"settings", "sensors", "ponics-settings", "light-settings"}:
            move_setting(1)

    @bindings.add("f1")
    def _help(event) -> None:
        switch_view("help")

    @bindings.add("f2")
    def _settings(event) -> None:
        switch_view("settings")

    @bindings.add("f3")
    def _status(event) -> None:
        switch_view("status")

    @bindings.add("f4")
    def _devices(event) -> None:
        switch_view("devices")

    @bindings.add("f5")
    def _ports(event) -> None:
        if ctx.view in {"settings", "sensors", "ponics-settings", "light-settings"}:
            run_line("light apply" if ctx.view == "light-settings" else "settings apply")
        else:
            switch_view("ports")

    @bindings.add("f6")
    def _log(event) -> None:
        switch_view("log")

    @bindings.add("escape")
    def _back(event) -> None:
        ctx.view, previous_view[0] = previous_view[0], ctx.view
        ctx.notice = ""
        app.invalidate()

    @bindings.add("escape", "a")
    def _apply(event) -> None:
        run_line("light apply" if ctx.view == "light-settings" else "settings apply")

    @bindings.add("c-s")
    def _save(event) -> None:
        run_line("light save" if ctx.view == "light-settings" else "settings save")

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
        full_screen=True, mouse_support=True,
        style=Style.from_dict({
            "title": "bold", "selected": "reverse", "status": "bg:#444444 #ffffff",
            "heading": "bold", "sensor_on": "bold #ff5f57", "output_on": "bold #ff5f57",
            "running": "bold #00aa00", "ok": "#00aa00", "inactive": "#888888",
            "warning": "bold #d7af00", "fault": "bold #ff0000", "demo": "#888888",
        }),
    )
    stop = threading.Event()
    ctx.screen_mode = True

    def refresh() -> None:
        while not stop.wait(ctx.settings.ui_interval_ms / 1000.0):
            app.invalidate()

    thread = threading.Thread(target=refresh, name="bionic-ui-refresh", daemon=True)
    thread.start()
    try:
        app.run()
    finally:
        ctx.screen_mode = False
        stop.set()
        thread.join(timeout=1)
