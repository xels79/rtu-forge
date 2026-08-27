from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from .commands import CommandContext, execute_command
from .completion import RTUForgeCompleter


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
        state = "CONNECTED" if ctx.transport.connected else "DISCONNECTED"
        return f" {state} | {ctx.transport.endpoint} "

    console.print("[bold]RTU Forge[/bold] interactive shell. Type [cyan]help[/cyan].")

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
                console.print(f"Capturing script [bold]{name}[/bold]. Finish with [cyan]end script[/cyan].")
                lines: list[str] = []
                while True:
                    script_line = session.prompt("... ", bottom_toolbar=toolbar)
                    if script_line.strip().lower() == "end script":
                        break
                    lines.append(script_line)
                ctx.scripts.set(name, lines)
                console.print(f"[green]Saved[/green] script '{name}' ({len(lines)} commands).")
            elif action == "history-show":
                try:
                    entries = list(session.history.get_strings())
                    limit = ctx.config["history"].getint("max_entries", fallback=2000)
                    for item in entries[-min(limit, 50):]:
                        console.print(item)
                except Exception as exc:
                    console.print(f"[red]History error:[/red] {exc}")
            elif action == "history-clear":
                history_path.write_text("", encoding="utf-8")
                console.print("[green]History file cleared.[/green] Restart shell to clear in-memory history.")
        except Exception as exc:
            console.print(f"[red]Error:[/red] {exc}")

    ctx.transport.disconnect()
