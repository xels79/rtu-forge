#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    printf '%s\n' \
        "Do not run setup.sh with sudo/root." \
        "RTU Forge is installed for the current user only." >&2
    exit 1
fi

usage() {
    cat <<'EOF'
Usage: ./setup.sh [options]

Install RTU Forge for the current Linux user without sudo.

Options:
  --repo-root PATH     Git/source directory (default: directory containing setup.sh)
  --data-dir PATH      RTUFORGE_HOME and user data directory
  --working-dir PATH   Working directory for the optional desktop launcher
  --install-dir PATH   Installation environment directory
  --bin-dir PATH       Directory for the rtuforge launcher
  --no-migrate         Do not copy existing config/scripts/history from RepoRoot
  --desktop            Create ~/.local/share/applications/rtu-forge.desktop
  --no-path-update     Do not update ~/.bashrc or ~/.zshrc
  -h, --help           Show this help
EOF
}

ORIGINAL_CWD=$(pwd -P)
SCRIPT_DIR=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

REPO_ROOT_RAW=$SCRIPT_DIR
DATA_DIR_RAW=${XDG_CONFIG_HOME:-$HOME/.config}/rtu-forge
INSTALL_DIR_RAW=${XDG_DATA_HOME:-$HOME/.local/share}/rtu-forge
BIN_DIR_RAW=$HOME/.local/bin
WORKING_DIR_RAW=
MIGRATE=1
CREATE_DESKTOP=0
UPDATE_PATH=1

while [ "$#" -gt 0 ]; do
    case "$1" in
        --repo-root|--data-dir|--working-dir|--install-dir|--bin-dir)
            if [ "$#" -lt 2 ]; then
                printf 'Missing value for %s\n' "$1" >&2
                exit 2
            fi
            case "$1" in
                --repo-root) REPO_ROOT_RAW=$2 ;;
                --data-dir) DATA_DIR_RAW=$2 ;;
                --working-dir) WORKING_DIR_RAW=$2 ;;
                --install-dir) INSTALL_DIR_RAW=$2 ;;
                --bin-dir) BIN_DIR_RAW=$2 ;;
            esac
            shift 2
            ;;
        --no-migrate) MIGRATE=0; shift ;;
        --desktop) CREATE_DESKTOP=1; shift ;;
        --no-path-update) UPDATE_PATH=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

normalize_path() {
    local value=$1
    case "$value" in
        "~") value=$HOME ;;
        "~/"*) value=$HOME/${value#\~/} ;;
    esac
    case "$value" in
        /*) realpath -m -- "$value" ;;
        *) realpath -m -- "$ORIGINAL_CWD/$value" ;;
    esac
}

REPO_ROOT=$(normalize_path "$REPO_ROOT_RAW")
DATA_DIR=$(normalize_path "$DATA_DIR_RAW")
INSTALL_DIR=$(normalize_path "$INSTALL_DIR_RAW")
BIN_DIR=$(normalize_path "$BIN_DIR_RAW")
if [ -n "$WORKING_DIR_RAW" ]; then
    WORKING_DIR=$(normalize_path "$WORKING_DIR_RAW")
else
    WORKING_DIR=$DATA_DIR
fi

if [ ! -f "$REPO_ROOT/pyproject.toml" ]; then
    printf 'RepoRoot does not contain pyproject.toml: %s\n' "$REPO_ROOT" >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    printf 'uv is required but was not found in PATH. Install uv and rerun setup.sh.\n' >&2
    exit 1
fi

mkdir -p -- "$DATA_DIR" "$WORKING_DIR" "$INSTALL_DIR" "$BIN_DIR"

VENV_DIR=$INSTALL_DIR/venv
if [ ! -x "$VENV_DIR/bin/python" ]; then
    uv venv "$VENV_DIR"
fi
uv pip install --python "$VENV_DIR/bin/python" -e "$REPO_ROOT"

if [ "$MIGRATE" -eq 1 ]; then
    for name in config.ini scripts.ini .rtuforge_history; do
        if [ -f "$REPO_ROOT/$name" ] && [ ! -e "$DATA_DIR/$name" ]; then
            cp -- "$REPO_ROOT/$name" "$DATA_DIR/$name"
            printf 'Migrated without overwrite: %s\n' "$DATA_DIR/$name"
        fi
    done
fi

LAUNCHER=$BIN_DIR/rtuforge
"$VENV_DIR/bin/python" - "$LAUNCHER" "$DATA_DIR" "$VENV_DIR/bin/rtuforge" <<'PY'
from pathlib import Path
import shlex
import sys

launcher, data_dir, executable = map(Path, sys.argv[1:])
text = (
    "#!/bin/sh\n"
    f"export RTUFORGE_HOME={shlex.quote(str(data_dir))}\n"
    f"exec {shlex.quote(str(executable))} \"$@\"\n"
)
launcher.write_text(text, encoding="utf-8", newline="\n")
PY
chmod 755 -- "$LAUNCHER"

DESKTOP_ENTRY="not created"
if [ "$CREATE_DESKTOP" -eq 1 ]; then
    DESKTOP_DIR=$(normalize_path "$HOME/.local/share/applications")
    mkdir -p -- "$DESKTOP_DIR"
    DESKTOP_FILE=$DESKTOP_DIR/rtu-forge.desktop
    "$VENV_DIR/bin/python" - "$DESKTOP_FILE" "$LAUNCHER" "$WORKING_DIR" <<'PY'
from pathlib import Path
import sys

desktop, launcher, working_dir = map(Path, sys.argv[1:])

def desktop_exec_quote(value: str) -> str:
    escaped = (
        value.replace("%", "%%")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'


def desktop_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )

desktop.write_text(
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=RTU Forge\n"
    "Comment=Modbus RTU console\n"
    f"Exec={desktop_exec_quote(str(launcher))}\n"
    f"Path={desktop_string(str(working_dir))}\n"
    "Terminal=true\n"
    "Categories=Development;Utility;\n",
    encoding="utf-8",
    newline="\n",
)
PY
    chmod 644 -- "$DESKTOP_FILE"
    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$DESKTOP_FILE"
    fi
    DESKTOP_ENTRY=$DESKTOP_FILE
fi

PATH_STATUS="already available"
EXPORT_COMMAND="export PATH=$(printf '%q' "$BIN_DIR"):\$PATH"
if [ "$UPDATE_PATH" -eq 0 ]; then
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            PATH_STATUS="not updated"
            printf 'BinDir is not in PATH. Add it with:\n  %s\n' "$EXPORT_COMMAND"
            ;;
    esac
else
    SHELL_NAME=$(basename -- "${SHELL:-}")
    case "$SHELL_NAME" in
        bash) RC_FILE=$HOME/.bashrc ;;
        zsh) RC_FILE=$HOME/.zshrc ;;
        *)
            RC_FILE=
            PATH_STATUS="not updated"
            printf 'Unknown shell. Add BinDir manually with:\n  %s\n' "$EXPORT_COMMAND"
            ;;
    esac
    if [ -n "$RC_FILE" ]; then
        touch -- "$RC_FILE"
        "$VENV_DIR/bin/python" - "$RC_FILE" "$BIN_DIR" <<'PY'
from pathlib import Path
import re
import shlex
import sys

rc_file = Path(sys.argv[1])
bin_dir = sys.argv[2]
opening = "# >>> RTU Forge >>>"
closing = "# <<< RTU Forge <<<"
block = f"{opening}\nexport PATH={shlex.quote(bin_dir)}:$PATH\n{closing}\n"
text = rc_file.read_text(encoding="utf-8")
pattern = re.compile(
    rf"(?ms)^{re.escape(opening)}\n.*?^{re.escape(closing)}(?:\n|$)"
)
without_blocks = pattern.sub("", text)
if without_blocks and not without_blocks.endswith("\n"):
    without_blocks += "\n"
if without_blocks and not without_blocks.endswith("\n\n"):
    without_blocks += "\n"
updated = f"{without_blocks}{block}"
rc_file.write_text(updated, encoding="utf-8", newline="\n")
PY
        PATH_STATUS="managed block updated in $RC_FILE"
        printf 'Open a new terminal or reload your shell.\n'
    fi
fi

USER_GROUPS=$(id -nG)
printf 'User groups: %s\n' "$USER_GROUPS"
case " $USER_GROUPS " in
    *" dialout "*|*" uucp "*|*" tty "*) ;;
    *)
        printf '%s\n' \
            'Warning: no common serial-access group (dialout/uucp/tty) was detected.' \
            'RTU Forge does not modify groups. See README: Serial permissions on Linux.'
        ;;
esac

printf 'Running self-check...\n'
"$LAUNCHER" --help >/dev/null
"$LAUNCHER" paths

printf '\nRepository:    %s\n' "$REPO_ROOT"
printf 'Data/Home:     %s\n' "$DATA_DIR"
printf 'Working dir:   %s\n' "$WORKING_DIR"
printf 'Install dir:   %s\n' "$INSTALL_DIR"
printf 'Bin dir:       %s\n' "$BIN_DIR"
printf 'Executable:    %s\n' "$LAUNCHER"
printf 'Config:        %s\n' "$DATA_DIR/config.ini"
printf 'Scripts:       %s\n' "$DATA_DIR/scripts.ini"
printf 'History:       %s\n' "$DATA_DIR/.rtuforge_history"
printf 'Desktop entry: %s\n' "$DESKTOP_ENTRY"
printf 'PATH status:   %s\n' "$PATH_STATUS"
