from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from .commands import CommandContext, execute_command
from .completion import RTUForgeCompleter
from .runtime_text import tr


def toolbar_text(ctx: CommandContext) -> str:
    state = tr(ctx.language, "connected_state" if ctx.transport.connected else "disconnected_state")
    return f" {state} | {ctx.transport.endpoint} "


def run_shell(ctx: CommandContext) -> None:
    history_path = Path(ctx.config["history"].get("file", ".rtuforge_history"))
    if not history_path.is_absolute():
        history_path = ctx.config_path.parent / history_path
    session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=RTUForgeCompleter(ctx.scripts, ctx.config.sections()),
        complete_while_typing=False,
    )
    console: Console = ctx.console

    def toolbar() -> str:
        return toolbar_text(ctx)

    console.print(tr(ctx.language, "shell_banner"), markup=False)

    while True:
        try:
            line = session.prompt("rtu> ", bottom_toolbar=toolbar)
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        try:
            action = execute_command(ctx, line)
            if action == "exit":
                break
            if action == "clear-screen":
                console.clear()
            elif action and action.startswith("add-script:"):
                name = action.split(":", 1)[1]
                console.print(tr(ctx.language, "capture_script", name=name), markup=False)
                lines: list[str] = []
                while True:
                    script_line = session.prompt("... ", bottom_toolbar=toolbar)
                    if script_line.strip().lower() == "end script":
                        break
                    lines.append(script_line)
                ctx.scripts.set(name, lines)
                console.print(tr(ctx.language, "script_saved", name=name, count=len(lines)), markup=False)
            elif action == "history-show":
                try:
                    entries = list(session.history.get_strings())
                    limit = ctx.config["history"].getint("max_entries", fallback=2000)
                    for item in entries[-min(limit, 50):]:
                        console.print(item, markup=False)
                except Exception as exc:
                    console.print(tr(ctx.language, "history_error", error=exc), markup=False)
            elif action == "history-clear":
                history_path.write_text("", encoding="utf-8")
                console.print(tr(ctx.language, "history_cleared"), markup=False)
        except KeyboardInterrupt:
            ctx.transport.disconnect()
            console.print()
        except Exception as exc:
            console.print(tr(ctx.language, "error", error=exc), markup=False)

    ctx.transport.disconnect()
