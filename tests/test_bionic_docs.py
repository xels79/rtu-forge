from pathlib import Path

from rtuforge.bionic_cli import execute_command, make_context
from rtuforge.bionic_config import OPTION_SPECS


ROOT = Path(__file__).parents[1]
GUIDE = ROOT / "docs" / "BIONIC-IMMITATOR-USER-GUIDE.md"


def test_user_guide_has_exact_32_linked_sections_and_all_settings():
    text = GUIDE.read_text(encoding="utf-8")
    anchors = (
        "purpose", "stand", "wiring", "requirements", "windows", "linux",
        "first-run", "ports", "controller", "relay", "contacts", "virtual-devices",
        "tui", "simulation", "tanks", "thresholds", "pumps", "drives", "pressure",
        "lights", "ponics", "chemistry", "faults", "dry-run", "saving-settings",
        "checkpoints", "journal", "tests", "troubleshooting", "commands",
        "configuration", "limitations",
    )
    assert len(anchors) == 32
    for index, anchor in enumerate(anchors, 1):
        assert f"](#{anchor})" in text
        assert f'<a id="{anchor}"></a>' in text
        assert f"## {index}. " in text
    for name in OPTION_SPECS:
        assert f"`{name}`" in text


def test_guide_local_images_and_readme_link_exist():
    text = GUIDE.read_text(encoding="utf-8")
    for name in (
        "sensors.svg", "equipment.svg", "pressure.svg", "faults.svg",
        "drive-hp1.svg", "light.svg", "ponics.svg", "settings.svg",
    ):
        assert f"bionic-screenshots/{name}" in text
        assert (GUIDE.parent / "bionic-screenshots" / name).exists()
    assert "docs/BIONIC-IMMITATOR-USER-GUIDE.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_new_documented_commands_execute(tmp_path):
    ctx = make_context(tmp_path)
    execute_command(ctx, "equipment set hp1 failure_s 240 --sync-wear")
    execute_command(ctx, "settings apply")
    execute_command(ctx, "settings save")
    execute_command(ctx, "sim state save test-1")
    execute_command(ctx, "sim state list")
    execute_command(ctx, "sim state load test-1 --confirm")
