from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from .commands import CommandContext, execute_command
from .config import load_config
from .scripts import ScriptStore
from .shell import run_shell
from .transport import SerialTransport


CLI_HELP_EPILOG = """examples:
  rtuforge                         interactive mode
  rtuforge shell                   interactive mode
  rtuforge send 01 03 00 65 00 01
  rtuforge run script read-basic
  rtuforge options
  rtuforge options connection
  rtuforge set options port COM7
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtuforge",
        description="RTU Forge - Modbus RTU console and script runner",
        epilog=CLI_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default="config.ini", help="Path to settings INI")
    parser.add_argument("--scripts", default="scripts.ini", help="Path to scripts INI")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="One-shot command; omit for interactive shell")
    return parser


def main() -> None:
    args = build_parser().parse_args()
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
    finally:
        ctx.transport.disconnect()


if __name__ == "__main__":
    main()
