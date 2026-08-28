from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class LinuxUserPaths:
    data_dir: Path
    working_dir: Path
    install_dir: Path
    bin_dir: Path


@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    config: Path
    scripts: Path


def _absolute(value: str | Path, cwd: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def linux_user_paths(environment: Mapping[str, str] | None = None) -> LinuxUserPaths:
    env = os.environ if environment is None else environment
    home = Path(env["HOME"]).expanduser().resolve()
    config_root = Path(env.get("XDG_CONFIG_HOME", home / ".config")).expanduser().resolve()
    data_root = Path(env.get("XDG_DATA_HOME", home / ".local" / "share")).expanduser().resolve()
    data_dir = (config_root / "rtu-forge").resolve()
    return LinuxUserPaths(
        data_dir=data_dir,
        working_dir=data_dir,
        install_dir=(data_root / "rtu-forge").resolve(),
        bin_dir=(home / ".local" / "bin").resolve(),
    )


def platform_default_home(
    environment: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
) -> Path:
    env = os.environ if environment is None else environment
    current_platform = sys.platform if platform is None else platform
    if current_platform == "win32":
        appdata = env.get("APPDATA")
        if appdata:
            return (Path(appdata).expanduser() / "RTUForge").resolve()
        profile = Path(env.get("USERPROFILE", Path.home())).expanduser()
        return (profile / "AppData" / "Roaming" / "RTUForge").resolve()

    home = Path(env.get("HOME", Path.home())).expanduser()
    config_root = Path(env.get("XDG_CONFIG_HOME", home / ".config")).expanduser()
    return (config_root / "rtu-forge").resolve()


def runtime_home(
    environment: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
) -> Path:
    env = os.environ if environment is None else environment
    configured = env.get("RTUFORGE_HOME")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError("RTUFORGE_HOME must be an absolute path")
        return path.resolve()
    return platform_default_home(env, platform=platform)


def resolve_runtime_paths(
    *,
    home: str | Path | None = None,
    config: str | Path | None = None,
    scripts: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    platform: str | None = None,
) -> RuntimePaths:
    base_cwd = Path.cwd().resolve() if cwd is None else Path(cwd).resolve()
    resolved_home = (
        _absolute(home, base_cwd)
        if home is not None
        else runtime_home(environment, platform=platform)
    )
    return RuntimePaths(
        home=resolved_home,
        config=_absolute(config, base_cwd) if config is not None else resolved_home / "config.ini",
        scripts=_absolute(scripts, base_cwd) if scripts is not None else resolved_home / "scripts.ini",
    )


def default_config_path(environment: Mapping[str, str] | None = None) -> Path:
    return resolve_runtime_paths(environment=environment).config


def default_scripts_path(environment: Mapping[str, str] | None = None) -> Path:
    return resolve_runtime_paths(environment=environment).scripts


def default_history_path(home: Path) -> Path:
    return home / ".rtuforge_history"
