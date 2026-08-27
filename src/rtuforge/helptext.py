from __future__ import annotations

from .i18n import GENERAL_HELP, HELP

# Compatibility aliases for code/tests that imported the original English registries.
# New runtime code should use i18n.command_help() and i18n.interactive_help().
COMMAND_HELP: dict[str, str] = HELP["en"]
INTERACTIVE_HELP: str = GENERAL_HELP["en"]
