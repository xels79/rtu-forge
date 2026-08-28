from __future__ import annotations

import re
import shutil
import subprocess
import os
import shlex
from pathlib import Path

import pytest


SETUP = Path("setup.sh")


def linux_tools() -> tuple[str, str]:
    if os.name != "posix":
        pytest.skip("Linux/POSIX integration test")
    if os.geteuid() == 0:
        pytest.skip("setup.sh intentionally refuses root")
    bash = shutil.which("bash")
    uv = shutil.which("uv")
    if bash is None or uv is None:
        pytest.skip("bash and uv are required for the Linux integration test")
    return bash, uv


def setup_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.setdefault("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
            "SHELL": "/bin/bash",
        }
    )
    Path(environment["HOME"]).mkdir(parents=True)
    return environment


def run_setup(
    bash: str,
    tmp_path: Path,
    environment: dict[str, str],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [bash, str(SETUP.resolve()), "--repo-root", str(Path.cwd().resolve()), *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed


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


def test_real_setup_migration_launcher_paths_and_rerun_preserve_data(tmp_path):
    bash, _ = linux_tools()
    environment = setup_environment(tmp_path)
    data = tmp_path / "data"
    work = tmp_path / "work"
    install = tmp_path / "install"
    bin_dir = tmp_path / "bin"
    invocation_cwd = tmp_path / "invocation"
    invocation_cwd.mkdir()
    arguments = (
        "--data-dir", str(data),
        "--working-dir", str(work),
        "--install-dir", str(install),
        "--bin-dir", str(bin_dir),
        "--no-path-update",
    )

    run_setup(bash, invocation_cwd, environment, *arguments)
    launcher = bin_dir / "rtuforge"
    assert launcher.is_file()
    assert (install / "venv" / "bin" / "python").is_file()
    for name in ("config.ini", "scripts.ini"):
        assert (data / name).read_bytes() == (Path.cwd() / name).read_bytes()

    help_result = subprocess.run(
        [str(launcher), "--help"], env=environment, capture_output=True, text=True, check=False
    )
    assert help_result.returncode == 0, help_result.stderr
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    paths_result = subprocess.run(
        [str(launcher), "paths"],
        cwd=elsewhere,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert paths_result.returncode == 0, paths_result.stderr
    compact = paths_result.stdout.replace("\n", "")
    assert str(data.resolve()) in compact
    assert str((data / "config.ini").resolve()) in compact
    assert str((data / "scripts.ini").resolve()) in compact
    assert not (elsewhere / "config.ini").exists()
    assert not (elsewhere / "scripts.ini").exists()

    history = data / ".rtuforge_history"
    history.write_text("history sentinel\n", encoding="utf-8")
    with (data / "config.ini").open("a", encoding="utf-8") as stream:
        stream.write("\n# config sentinel\n")
    with (data / "scripts.ini").open("a", encoding="utf-8") as stream:
        stream.write("\n# scripts sentinel\n")
    before = {path.name: path.read_bytes() for path in (data / "config.ini", data / "scripts.ini", history)}
    run_setup(bash, invocation_cwd, environment, *arguments)
    assert {path.name: path.read_bytes() for path in (data / "config.ini", data / "scripts.ini", history)} == before
    assert list(invocation_cwd.iterdir()) == []


def test_no_migrate_preserves_existing_config_and_status_works(tmp_path):
    bash, _ = linux_tools()
    environment = setup_environment(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    for name in ("config.ini", "scripts.ini"):
        target = data / name
        target.write_bytes((Path.cwd() / name).read_bytes() + b"\n# no-migrate sentinel\n")
    before = {path.name: path.read_bytes() for path in data.iterdir()}
    bin_dir = tmp_path / "bin"

    run_setup(
        bash,
        tmp_path,
        environment,
        "--data-dir", str(data),
        "--working-dir", str(tmp_path / "work"),
        "--install-dir", str(tmp_path / "install"),
        "--bin-dir", str(bin_dir),
        "--no-migrate",
        "--no-path-update",
    )

    assert {path.name: path.read_bytes() for path in data.iterdir()} == before
    status = subprocess.run(
        [str(bin_dir / "rtuforge"), "status"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0, status.stdout + status.stderr


def test_no_migrate_fresh_data_allows_help_and_paths_but_status_reports_config(tmp_path):
    bash, _ = linux_tools()
    environment = setup_environment(tmp_path)
    data = tmp_path / "empty-data"
    bin_dir = tmp_path / "bin"

    run_setup(
        bash,
        tmp_path,
        environment,
        "--data-dir", str(data),
        "--working-dir", str(tmp_path / "work"),
        "--install-dir", str(tmp_path / "install"),
        "--bin-dir", str(bin_dir),
        "--no-migrate",
        "--no-path-update",
    )

    launcher = bin_dir / "rtuforge"
    assert not (data / "config.ini").exists()
    assert not (data / "scripts.ini").exists()
    for arguments in (["--help"], ["paths"]):
        result = subprocess.run(
            [str(launcher), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    status = subprocess.run(
        [str(launcher), "status"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode != 0
    assert "Config file not found" in status.stdout + status.stderr
    assert "Traceback" not in status.stdout + status.stderr


def test_setup_ignores_relative_xdg_roots_for_default_directories(tmp_path):
    bash, _ = linux_tools()
    environment = setup_environment(tmp_path)
    environment["XDG_CONFIG_HOME"] = "relative-config"
    environment["XDG_DATA_HOME"] = "relative-data"
    invocation_cwd = tmp_path / "invocation"
    invocation_cwd.mkdir()

    run_setup(
        bash,
        invocation_cwd,
        environment,
        "--working-dir", str(tmp_path / "work"),
        "--bin-dir", str(tmp_path / "bin"),
        "--no-migrate",
        "--no-path-update",
    )

    home = Path(environment["HOME"])
    assert (home / ".config" / "rtu-forge").is_dir()
    assert (home / ".local" / "share" / "rtu-forge" / "venv" / "bin" / "python").is_file()
    assert not (invocation_cwd / "relative-config").exists()
    assert not (invocation_cwd / "relative-data").exists()


def test_setup_updates_managed_path_block_and_preserves_rc_content(tmp_path):
    bash, _ = linux_tools()
    environment = setup_environment(tmp_path)
    bashrc = Path(environment["HOME"]) / ".bashrc"
    bashrc.write_text("# keep this user line\nexport USER_SETTING=yes\n", encoding="utf-8")
    common = (
        "--data-dir", str(tmp_path / "data"),
        "--working-dir", str(tmp_path / "work"),
        "--install-dir", str(tmp_path / "install"),
        "--no-migrate",
    )
    bin_a = tmp_path / "bin-a"
    bin_b = tmp_path / "bin b"
    run_setup(bash, tmp_path, environment, *common, "--bin-dir", str(bin_a))
    run_setup(bash, tmp_path, environment, *common, "--bin-dir", str(bin_b))
    text = bashrc.read_text(encoding="utf-8")
    assert text.count("# >>> RTU Forge >>>") == 1
    assert text.count("# <<< RTU Forge <<<") == 1
    assert text.count("export PATH=") == 1
    assert shlex.quote(str(bin_b.resolve())) in text
    assert str(bin_a.resolve()) not in text
    assert "# keep this user line" in text
    assert "export USER_SETTING=yes" in text


def test_setup_desktop_entry_uses_distinct_exec_and_path_escaping(tmp_path):
    bash, _ = linux_tools()
    environment = setup_environment(tmp_path)
    work = tmp_path / "work with spaces"
    bin_dir = tmp_path / "bin with spaces"
    run_setup(
        bash,
        tmp_path,
        environment,
        "--data-dir", str(tmp_path / "data"),
        "--working-dir", str(work),
        "--install-dir", str(tmp_path / "install"),
        "--bin-dir", str(bin_dir),
        "--no-migrate",
        "--no-path-update",
        "--desktop",
    )
    desktop = Path(environment["HOME"]) / ".local/share/applications/rtu-forge.desktop"
    values = dict(
        line.split("=", 1)
        for line in desktop.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert shlex.split(values["Exec"].replace("%%", "%")) == [str((bin_dir / "rtuforge").resolve())]
    assert values["Path"] == str(work.resolve())
    assert values["Terminal"] == "true"
