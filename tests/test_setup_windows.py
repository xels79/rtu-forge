from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


SETUP = Path("setup.ps1")


def test_setup_ps1_exists_and_declares_supported_parameters():
    text = SETUP.read_text(encoding="utf-8")
    for parameter in ("RepoRoot", "DataDir", "WorkingDir", "NoShortcut", "NoMigrate"):
        assert re.search(rf"\${parameter}\b", text)
    assert "Resolve-Path" not in text
    assert "ConvertTo-AbsolutePath" in text


def test_setup_ps1_uses_uv_tool_reported_executable_and_user_environment():
    text = SETUP.read_text(encoding="utf-8")
    assert "uv tool install --editable $RepoRoot --force" in text
    assert "uv tool update-shell" in text
    assert "uv tool dir --bin" in text
    assert 'Join-Path -Path $ToolBin -ChildPath "rtuforge.exe"' in text
    assert '[Environment]::SetEnvironmentVariable("RTUFORGE_HOME", $DataDir, "User")' in text
    assert 'SetEnvironmentVariable("RTUFORGE_HOME", $DataDir, "Machine")' not in text
    assert "Administrator" not in text


def test_setup_ps1_migration_is_copy_only_and_guarded_against_overwrite():
    text = SETUP.read_text(encoding="utf-8")
    assert "if (-not $NoMigrate)" in text
    assert "-not (Test-Path -LiteralPath $Destination)" in text
    assert "Copy-Item -LiteralPath $Source -Destination $Destination" in text
    assert "Move-Item" not in text
    assert "Remove-Item" not in text


def test_setup_ps1_shortcut_and_self_check_are_explicit():
    text = SETUP.read_text(encoding="utf-8")
    assert "$Shortcut.TargetPath = $RtuForgeExe" in text
    assert "$Shortcut.Arguments" in text
    assert "--home" in text
    assert "$Shortcut.WorkingDirectory = $WorkingDir" in text
    assert "& $RtuForgeExe --help" in text
    assert "& $RtuForgeExe paths" in text


def test_setup_ps1_parses_when_pwsh_is_available():
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is not available")
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "(Resolve-Path -LiteralPath 'setup.ps1'), [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    completed = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
