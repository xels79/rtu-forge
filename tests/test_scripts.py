from pathlib import Path

from rtuforge.scripts import ScriptStore
import pytest


def test_script_roundtrip(tmp_path: Path):
    path = tmp_path / "scripts.ini"
    store = ScriptStore(path)
    store.set("demo", ["send 01 03 00 65 00 01", "pause 100"])
    assert store.list() == ["demo"]
    assert store.get("demo") == ["send 01 03 00 65 00 01", "pause 100"]


def test_script_names_keep_case_spaces_and_unicode(tmp_path: Path):
    store = ScriptStore(tmp_path / "scripts.ini")
    store.set("Тест ПЧ", ["pause 1"])
    store.set("Motor status", ["pause 2"])
    assert store.get("Тест ПЧ") == ["pause 1"]
    assert "Motor status" in store.list()


@pytest.mark.parametrize("name", ["", "   ", "bad=name", "bad:name", "bad\nname", "bad\rname"])
def test_invalid_script_names_are_rejected(tmp_path: Path, name: str):
    with pytest.raises(ValueError):
        ScriptStore(tmp_path / "scripts.ini").set(name, ["pause 1"])


def test_set_many_conflict_is_atomic(tmp_path: Path):
    path = tmp_path / "scripts.ini"
    store = ScriptStore(path)
    store.set("existing", ["pause 1"])
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        store.set_many({"new": ["pause 2"], "existing": ["pause 3"]})
    assert path.read_bytes() == before
    assert store.list() == ["existing"]
