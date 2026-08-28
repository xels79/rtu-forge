from pathlib import Path

import pytest

from rtuforge.script_file import load_script_file, save_script_file


def test_single_and_multi_roundtrip_preserve_names_and_order(tmp_path: Path):
    single = tmp_path / "single.rtus"
    save_script_file(single, {"Motor status": ["send 01 03", "pause 100"]})
    assert load_script_file(single) == {"Motor status": ["send 01 03", "pause 100"]}

    bundle = tmp_path / "bundle.rtus"
    expected = {"Тест ПЧ": ["pause 1"], "Empty": []}
    save_script_file(bundle, expected)
    assert load_script_file(bundle) == expected
    assert bundle.read_text(encoding="utf-8").startswith("# RTU Forge script file")


def test_utf8_bom_is_accepted(tmp_path: Path):
    path = tmp_path / "bom.rtus"
    path.write_text("[rtuforge]\nformat = scripts-v1\n[scripts]\nТест =\n    pause 1\n", encoding="utf-8-sig")
    assert load_script_file(path) == {"Тест": ["pause 1"]}


@pytest.mark.parametrize(
    "text,match",
    [
        ("[scripts]\na = pause 1\n", "missing \\[rtuforge\\]"),
        ("[rtuforge]\nformat=scripts-v1\n", "missing \\[scripts\\]"),
        ("[rtuforge]\nformat=other\n[scripts]\n", "Unsupported"),
        ("[rtuforge\nformat=x", "Invalid script file"),
        ("[rtuforge]\nformat=scripts-v1\n[scripts]\na=pause 1\na=pause 2\n", "Invalid script file"),
        ("[rtuforge]\nformat=scripts-v1\n[scripts]\nbad:name=pause 1\n", "Script name"),
    ],
)
def test_invalid_files_are_rejected(tmp_path: Path, text: str, match: str):
    path = tmp_path / "bad.rtus"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_script_file(path)


def test_invalid_utf8_and_existing_destination_are_rejected(tmp_path: Path):
    path = tmp_path / "bad.rtus"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="UTF-8"):
        load_script_file(path)
    with pytest.raises(FileExistsError):
        save_script_file(path, {"demo": []})
    save_script_file(path, {"demo": []}, overwrite=True)
    assert load_script_file(path) == {"demo": []}
