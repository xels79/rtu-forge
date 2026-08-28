from __future__ import annotations

import argparse
import sys

from rich.console import Console

from .commands import CommandContext, execute_command
from .connection import parse_connection_overrides
from .config import load_config
from .i18n import cli_text
from .paths import default_history_path, resolve_runtime_paths
from .runtime_text import tr
from .scripts import ScriptStore
from .shell import run_shell
from .transport import SerialTransport


def _promote_clean_flag(argv: list[str]) -> list[str]:
    """Allow -c/--clean both before and after the one-shot command."""
    if not any(item in {"-c", "--clean"} for item in argv):
        return argv
    return ["--clean", *(item for item in argv if item not in {"-c", "--clean"})]


def _console(*, stderr: bool = False) -> Console:
    """Build an RTU Forge console without Rich's automatic token highlighting."""
    return Console(stderr=stderr, highlight=False)


def build_parser(language: str = "en") -> argparse.ArgumentParser:
    text = cli_text(language)
    is_ru = language.lower() == "ru"
    clean_help = (
        "Чистый HEX-вывод только для текущего запуска; config.ini не изменяется"
        if is_ru
        else "Use clean HEX output for this run only; config.ini is not changed"
    )
    detailed_help = (
        "Подробная справка по командам:\n"
        "  rtuforge help\n"
        "  rtuforge help scan\n"
        "  rtuforge help <command>\n"
        "В интерактивной консоли: help [command]"
        if is_ru
        else
        "Detailed command help:\n"
        "  rtuforge help\n"
        "  rtuforge help scan\n"
        "  rtuforge help <command>\n"
        "In the interactive shell: help [command]"
    )
    epilog = f"{text['epilog'].rstrip()}\n\n{detailed_help}"
    parser = argparse.ArgumentParser(
        prog="rtuforge",
        description=text["description"],
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help=text["help"])
    parser.add_argument("-c", "--clean", action="store_true", help=clean_help)
    parser.add_argument("--home", help=text["home"])
    parser.add_argument("--config", help=text["config"])
    parser.add_argument("--scripts", help=text["scripts"])
    connection_group = parser.add_argument_group(
        "Временные параметры соединения" if is_ru else "Temporary connection overrides",
        (
            "Действуют только до завершения процесса и не изменяют config.ini."
            if is_ru
            else "Apply only to the current process and do not modify config.ini."
        ),
    )
    connection_group.add_argument("--port", metavar="PORT")
    connection_group.add_argument("--baudrate", metavar="RATE")
    connection_group.add_argument("--bytesize", metavar="{5,6,7,8}")
    connection_group.add_argument("--parity", metavar="{N,E,O,M,S}")
    connection_group.add_argument("--stopbits", metavar="{1,1.5,2}")
    connection_group.add_argument("--timeout-ms", metavar="MS")
    parser.add_argument("command", nargs=argparse.REMAINDER, help=text["command"])
    return parser


def _language_for_argv(argv: list[str]) -> str:
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--home")
    probe.add_argument("--config")
    probe.add_argument("--scripts")
    probe_args, _ = probe.parse_known_args(argv)
    try:
        config_path = resolve_runtime_paths(
            home=probe_args.home,
            config=probe_args.config,
            scripts=probe_args.scripts,
        ).config
    except ValueError:
        return "en"
    if not config_path.exists():
        return "en"
    try:
        config = load_config(config_path)
    except Exception:
        return "en"
    return config.get("ui", "language", fallback="en")


def main() -> int:
    argv = _promote_clean_flag(sys.argv[1:])
    language = _language_for_argv(argv)
    args = build_parser(language).parse_args(argv)
    try:
        paths = resolve_runtime_paths(
            home=args.home,
            config=args.config,
            scripts=args.scripts,
        )
    except ValueError as exc:
        _console(stderr=True).print(tr(language, "error", error=exc), markup=False)
        return 1
    config_path = paths.config
    scripts_path = paths.scripts

    if args.command == ["paths"] and not config_path.exists():
        console = _console()
        console.print(f"Home:    {paths.home}", markup=False)
        console.print(f"Config:  {config_path}", markup=False)
        console.print(f"Scripts: {scripts_path}", markup=False)
        console.print(f"History: {default_history_path(paths.home)}", markup=False)
        return 0

    try:
        config = load_config(config_path)
    except Exception as exc:
        _console(stderr=True).print(tr(language, "error", error=exc), markup=False)
        return 1

    if args.clean:
        config["runtime"]["clean_output"] = "true"

    try:
        overrides = parse_connection_overrides(
            {
                "port": args.port,
                "baudrate": args.baudrate,
                "bytesize": args.bytesize,
                "parity": args.parity,
                "stopbits": args.stopbits,
                "timeout_ms": args.timeout_ms,
            }
        )
    except ValueError as exc:
        _console(stderr=True).print(
            tr(language, "invalid_connection_override", name=exc), markup=False
        )
        return 1

    console = _console()
    ctx = CommandContext(
        config_path=config_path,
        config=config,
        scripts=ScriptStore(scripts_path),
        transport=SerialTransport(config, overrides),
        console=console,
        home_path=paths.home,
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
        _console(stderr=True).print(tr(ctx.language, "error", error=exc), markup=False)
        return 1
    finally:
        ctx.transport.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
