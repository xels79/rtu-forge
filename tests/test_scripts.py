from pathlib import Path

from rtuforge.scripts import ScriptStore


def test_script_roundtrip(tmp_path: Path):
    path = tmp_path / "scripts.ini"
    store = ScriptStore(path)
    store.set("demo", ["send 01 03 00 65 00 01", "pause 100"])
    assert store.list() == ["demo"]
    assert store.get("demo") == ["send 01 03 00 65 00 01", "pause 100"]
