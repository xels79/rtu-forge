from pathlib import Path

from rich.console import Console

from rtuforge.bionic_cli import execute_command, make_context
from rtuforge.bionic_completion import completion_candidates
from rtuforge.bionic_history import CommandHistory
from rtuforge.bionic_render import VIEW_NAMES, render_page, visible_lines
from rtuforge.bionic_tui import clamp_scroll


def context(tmp_path: Path):
    console = Console(record=True, width=120)
    return make_context(tmp_path, console=console), console


def page(ctx, name: str, width: int = 120):
    return render_page(
        name, ctx.model, ctx.journal, ctx.settings, ctx.draft,
        ctx.saved or ctx.settings, width=width, log_filter=ctx.log_filter,
        help_query=ctx.help_query,
    )


def test_required_views_have_separate_content(tmp_path):
    ctx, _ = context(tmp_path)
    status = "\n".join(page(ctx, "status").lines)
    help_text = "\n".join(page(ctx, "help").lines)
    settings = "\n".join(page(ctx, "settings").lines)
    devices = "\n".join(page(ctx, "devices").lines)
    ports = "\n".join(page(ctx, "ports").lines)

    assert set(VIEW_NAMES) >= {"status", "devices", "ports", "settings", "help", "log"}
    assert "БАКИ" in status and "ПОСЛЕДНИЕ СОБЫТИЯ (3)" in status
    assert "ОБЩИЕ" not in status and "Техническое имя" not in status
    assert "ОБЩИЕ" in help_text and "БАКИ" in help_text and "Техническое имя" not in help_text
    assert "Техническое имя" in settings and "Время набора давления" in settings
    assert "Релейный модуль Waveshare 32CH" in devices and "Осмос" not in ports
    assert "USB №1" in ports and "БАКИ" not in ports


def test_status_has_exactly_three_recent_event_slots(tmp_path):
    ctx, _ = context(tmp_path)
    for index in range(5):
        ctx.event("БАК", "bo", f"event-{index}")
    text = "\n".join(page(ctx, "status").lines)
    assert "event-2" in text and "event-4" in text
    assert "event-1" not in text


def test_settings_show_draft_applied_and_saved_states(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "settings set pressure_rise_s 6")
    settings_page = page(ctx, "settings", 160)
    row = settings_page.row_keys.index("pressure_rise_s")
    assert "6.0 с" in settings_page.lines[row] and "-/-" in settings_page.lines[row]
    execute_command(ctx, "settings apply")
    settings_page = page(ctx, "settings", 160)
    assert "A/-" in settings_page.lines[row]
    execute_command(ctx, "settings save")
    settings_page = page(ctx, "settings", 160)
    assert "A/S" in settings_page.lines[row]


def test_narrow_pages_are_clipped_without_wrapping(tmp_path):
    ctx, _ = context(tmp_path)
    narrow = page(ctx, "devices", 32)
    assert all("\n" not in line and len(line) <= 32 for line in narrow.lines)
    assert any(line.endswith("...") for line in narrow.lines)
    assert "Русское" in narrow.lines[0]


def test_viewport_is_fixed_height_and_scroll_is_clamped(tmp_path):
    ctx, _ = context(tmp_path)
    help_page = page(ctx, "help")
    assert len(visible_lines(help_page, height=7, scroll=0)) == 7
    assert clamp_scroll(0, 1000, len(help_page.lines), 7) == max(0, len(help_page.lines) - 7)
    assert clamp_scroll(4, -1000, len(help_page.lines), 7) == 0


def test_history_persists_ignores_blanks_duplicates_and_caps(tmp_path):
    path = tmp_path / ".bionic-immitator-history"
    history = CommandHistory(path, limit=200)
    history.append("")
    history.append("status")
    history.append("status")
    for index in range(210):
        history.append(f"view item-{index}")
    restored = CommandHistory(path, limit=200)
    assert len(restored.entries) == 200
    assert restored.entries[-1] == "view item-209"
    assert all(restored.entries[index] != restored.entries[index - 1] for index in range(1, len(restored.entries)))


def test_completion_covers_nested_commands_and_names():
    assert completion_candidates("view se") == ["sensors", "settings"]
    assert completion_candidates("tank b") == ["bo", "bp", "bso1", "bso2"]
    assert completion_candidates("pump bo-to-bp ") == ["flow"]
    assert completion_candidates("sensor bo-") == ["bo-max", "bo-min"]
    assert completion_candidates("sensor bo-min ") == ["auto", "force", "threshold"]
    assert "pressure_rise_s" in completion_candidates("settings set pressure_")
    assert completion_candidates("log filter a") == ["alarms", "all"]
    assert "ai-pressure" in completion_candidates("devices ")


def test_screen_mode_commands_navigate_without_printing_dump(tmp_path):
    ctx, console = context(tmp_path)
    ctx.screen_mode = True
    execute_command(ctx, "help search pressure")
    assert ctx.view == "help" and ctx.help_query == "pressure"
    execute_command(ctx, "sensor list")
    assert ctx.view == "sensors"
    execute_command(ctx, "settings list")
    assert ctx.view == "settings"
    assert console.export_text() == ""
