from pathlib import Path

from rtuforge.paths import linux_user_paths, runtime_home


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
