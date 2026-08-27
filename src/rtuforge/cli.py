from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .commands import CommandContext, execute_command
from .config import load_config
from .i18n import cli_text
from .scripts import ScriptStore
from .shell import run_shell
from .transport import SerialTransport


def build_parser(language: str = "en") -> argparse.ArgumentParser:
    text = cli_text(language)
    parser = argparse.ArgumentParser(
        prog="rtuforge",
        description=text["description"],
        epilog=text["epilog"],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help=text["help"])
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


def main() -> None:
    argv = sys.argv[1:]
    language = _language_for_argv(argv)
    args = build_parser(language).parse_args(argv)
    config_path = Path(args.config).resolve()
    scripts_path = Path(args.scripts).resolve()
    config = load_config(config_path)
    console = Console()
    ctx = CommandContext(
        config_path=config_path,
        config=config,
        scripts=ScriptStore(scripts_path),
        transport=SerialTransport(config),
        console=console,
    )

    command = args.command
    if not command or command == ["shell"]:
        run_shell(ctx)
        return

    line = " ".join(command)
    try:
        action = execute_command(ctx, line)
        if action and action.startswith("add-script:"):
            raise ValueError("'add script' is available only in interactive mode")
        if action and action.startswith("history"):
            raise ValueError("history commands are available only in interactive mode")
        if action == "clear-screen":
            raise ValueError("clear/cls is available only in interactive mode")
    finally:
        ctx.transport.disconnect()


if __name__ == "__main__":
    main()
