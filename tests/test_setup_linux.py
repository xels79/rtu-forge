from __future__ import annotations

import re
import shutil
import subprocess
import os
from pathlib import Path

import pytest


SETUP = Path("setup.sh")


def test_setup_has_required_safety_and_options():
    text = SETUP.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert '"$(id -u)" -eq 0' in text
    assert "Do not run setup.sh with sudo/root." in text
    assert re.search(r"^\s*sudo\s", text, re.MULTILINE) is None
    assert re.search(r"^\s*usermod\s", text, re.MULTILINE) is None
    for option in (
        "--repo-root", "--data-dir", "--working-dir", "--install-dir",
        "--bin-dir", "--no-migrate", "--desktop", "--no-path-update",
    ):
        assert option in text


def test_setup_uses_editable_venv_safe_migration_and_exec_launcher():
    text = SETUP.read_text(encoding="utf-8")
    assert 'uv venv "$VENV_DIR"' in text
    assert 'uv pip install --python "$VENV_DIR/bin/python" -e "$REPO_ROOT"' in text
    assert '[ ! -e "$DATA_DIR/$name" ]' in text
    assert 'export RTUFORGE_HOME=' in text
    assert 'exec {shlex.quote(str(executable))} \\"$@\\"' in text
    assert "cd /usr" not in text


def test_setup_shell_syntax_when_bash_is_available():
    if os.name != "posix":
        pytest.skip("Linux/POSIX bash smoke check")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available on this test platform")
    completed = subprocess.run(
        [bash, "-n", str(SETUP.resolve())], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
