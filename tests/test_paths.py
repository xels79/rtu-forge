from pathlib import Path

import pytest

from rtuforge.paths import (
    linux_user_paths,
    platform_default_home,
    resolve_runtime_paths,
    runtime_home,
)


def test_linux_paths_use_xdg_directories(tmp_path):
    paths = linux_user_paths(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
            "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        }
    )
    assert paths.data_dir == (tmp_path / "xdg-config" / "rtu-forge").resolve()
    assert paths.install_dir == (tmp_path / "xdg-data" / "rtu-forge").resolve()
    assert paths.working_dir == paths.data_dir
    assert paths.bin_dir == (tmp_path / "home" / ".local" / "bin").resolve()
    assert all(path.is_absolute() for path in paths.__dict__.values())


def test_linux_paths_fall_back_to_home(tmp_path):
    paths = linux_user_paths({"HOME": str(tmp_path / "home")})
    assert paths.data_dir == (tmp_path / "home" / ".config" / "rtu-forge").resolve()
    assert paths.install_dir == (tmp_path / "home" / ".local" / "share" / "rtu-forge").resolve()


def test_runtime_home_honors_environment(tmp_path):
    assert runtime_home({"RTUFORGE_HOME": str(tmp_path / "data")}) == (tmp_path / "data").resolve()


def test_relative_runtime_home_is_rejected():
    with pytest.raises(ValueError, match="RTUFORGE_HOME must be an absolute path"):
        runtime_home({"RTUFORGE_HOME": "relative-data"})


def test_runtime_path_priority_and_relative_cli_paths(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env_home = tmp_path / "environment-home"
    paths = resolve_runtime_paths(
        home="cli-home",
        config="explicit/config.ini",
        scripts="explicit/scripts.ini",
        environment={"RTUFORGE_HOME": str(env_home)},
        cwd=cwd,
    )
    assert paths.home == (cwd / "cli-home").resolve()
    assert paths.config == (cwd / "explicit" / "config.ini").resolve()
    assert paths.scripts == (cwd / "explicit" / "scripts.ini").resolve()


def test_home_overrides_environment_for_default_files(tmp_path):
    cwd = tmp_path / "cwd"
    paths = resolve_runtime_paths(
        home="data",
        environment={"RTUFORGE_HOME": str(tmp_path / "environment-home")},
        cwd=cwd,
    )
    assert paths.home == (cwd / "data").resolve()
    assert paths.config == paths.home / "config.ini"
    assert paths.scripts == paths.home / "scripts.ini"


def test_platform_default_is_stable_across_cwd(tmp_path):
    environment = {
        "HOME": str(tmp_path / "user"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
    }
    first = resolve_runtime_paths(environment=environment, cwd=tmp_path / "one", platform="linux")
    second = resolve_runtime_paths(environment=environment, cwd=tmp_path / "two", platform="linux")
    assert first == second
    assert first.home == platform_default_home(environment, platform="linux")


def test_windows_platform_default_uses_appdata(tmp_path):
    home = platform_default_home({"APPDATA": str(tmp_path / "Roaming")}, platform="win32")
    assert home == (tmp_path / "Roaming" / "RTUForge").resolve()
