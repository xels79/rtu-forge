from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class LinuxUserPaths:
    data_dir: Path
    working_dir: Path
    install_dir: Path
    bin_dir: Path


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


def runtime_home(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    configured = env.get("RTUFORGE_HOME")
    return Path(configured).expanduser().resolve() if configured else Path.cwd().resolve()


def default_config_path(environment: Mapping[str, str] | None = None) -> Path:
    return runtime_home(environment) / "config.ini"


def default_scripts_path(environment: Mapping[str, str] | None = None) -> Path:
    return runtime_home(environment) / "scripts.ini"


def default_history_path(home: Path) -> Path:
    return home / ".rtuforge_history"
