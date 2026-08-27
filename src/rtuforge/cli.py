from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .commands import CommandContext, execute_command
from .config import load_config
from .i18n import cli_text
from .runtime_text import tr
from .scripts import ScriptStore
from .shell import run_shell
from .transport import SerialTransport


def _promote_clean_flag(argv: list[str]) -> list[str]:
    """Allow -c/--clean both before and after the one-shot command."""
    if not any(item in {"-c", "--clean"} for item in argv):
        return argv
    return ["--clean", *(item for item in argv if item not in {"-c", "--clean"})]


def build_parser(language: str = "en") -> argparse.ArgumentParser:
    text = cli_text(language)
    clean_help = (
        "Чистый HEX-вывод только для текущего запуска; config.ini не изменяется"
        if language.lower() == "ru"
        else "Use clean HEX output for this run only; config.ini is not changed"
    )
    parser = argparse.ArgumentParser(
        prog="rtuforge",
        description=text["description"],
        epilog=text["epilog"],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help=text["help"])
    parser.add_argument("-c", "--clean", action="store_true", help=clean_help)
    parser.add_argument("--config", default="config.ini", help=text["config"])
    parser.add_argument("--scripts", default="scripts.ini", help=text["scripts"])
    parser.add_argument("command", nargs=argparse.REMAINDER, help=text["command"])
    return parser


def _language_for_argv(argv: list[str]) -> str:
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--config", default="config.ini")
    probe_args, _ = probe.parse_known_args(argv)
    config_path = Path(probe_args.config).resolve()
    if not config_path.exists():
        return "en"
    config = load_config(config_path)
    return config.get("ui", "language", fallback="en")


def main() -> int:
    argv = _promote_clean_flag(sys.argv[1:])
    language = _language_for_argv(argv)
    args = build_parser(language).parse_args(argv)
    config_path = Path(args.config).resolve()
    scripts_path = Path(args.scripts).resolve()

    try:
        config = load_config(config_path)
    except Exception as exc:
        Console(stderr=True).print(tr(language, "error", error=exc), markup=False)
        return 1

    if args.clean:
        config["runtime"]["clean_output"] = "true"

    console = Console()
    ctx = CommandContext(
        config_path=config_path,
        config=config,
        scripts=ScriptStore(scripts_path),
        transport=SerialTransport(config),
        console=console,
        one_shot=True,
    )

    command = args.command
    if not command or command == ["shell"]:
        ctx.one_shot = False
        run_shell(ctx)
        return 0

    line = " ".join(command)
    try:
        action = execute_command(ctx, line)
        if action and action.startswith("add-script:"):
            raise ValueError(tr(ctx.language, "oneshot_add_script"))
        if action and action.startswith("history"):
            raise ValueError(tr(ctx.language, "oneshot_history"))
        if action == "clear-screen":
            raise ValueError(tr(ctx.language, "oneshot_clear"))
        return 0
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        Console(stderr=True).print(tr(ctx.language, "error", error=exc), markup=False)
        return 1
    finally:
        ctx.transport.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
