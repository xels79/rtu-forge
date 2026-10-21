from pathlib import Path
from dataclasses import replace

from rich.console import Console

from rtuforge.bionic_cli import execute_command, make_context
from rtuforge.bionic_completion import completion_candidates
from rtuforge.bionic_history import CommandHistory
from rtuforge.bionic_render import VIEW_NAMES, render_page, visible_lines
from rtuforge.bionic_sensor_bridge import SensorRelayState
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


def test_help_has_prominent_simulation_control_section(tmp_path):
    ctx, _ = context(tmp_path)
    text = "\n".join(page(ctx, "help").lines)
    assert "УПРАВЛЕНИЕ СИМУЛЯЦИЕЙ" in text
    assert "sim start            Запустить расчёт физики" in text
    assert "sim reset --confirm  Сбросить виртуальное состояние" in text
    assert "sim pause не закрывает RS485" in text
    assert "не отправляет плате команду остановки" in text


def test_every_page_exposes_fixed_simulation_status(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "sim start")
    for name in VIEW_NAMES:
        assert page(ctx, name).simulation_status == "СИМУЛЯЦИЯ: РАБОТАЕТ | СКОРОСТЬ: ×1.0"
    execute_command(ctx, "sim speed 5")
    execute_command(ctx, "sim pause")
    assert page(ctx, "pressure").simulation_status == "СИМУЛЯЦИЯ: ПАУЗА | СКОРОСТЬ: ×5.0"


def test_pressure_diagnostics_show_hydraulic_inputs_and_outputs(tmp_path):
    ctx, _ = context(tmp_path)
    text = "\n".join(page(ctx, "pressure", 180).lines)
    for expected in (
        "частота", "Ярусы открыты", "Клапаны ярусов", "Источник",
        "Расчётный расход", "HIGH, текущее давление", "Целевое давление модели",
        "Последний переходный скачок", "Максимальное зафиксированное давление",
        "Трубопровод", "после датчика HIGH",
    ):
        assert expected in text


def test_light_page_shows_all_tiers_voltage_brightness_and_effective_state(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.set_analog_output(2, 1, 7000)
    text = "\n".join(page(ctx, "light", 180).lines)
    assert all(f"zone-{index}" in text for index in range(1, 7))
    assert "Питание DO3: ВЫКЛ | фактический свет: ВЫКЛ" in text
    assert "Modbus ID 2 / AO1 | задание 7.000 В | яркость 70.0%" in text
    assert "Красный" in text and "Дальний красный" in text
    ctx.model.set_relay(3, True)
    assert "Питание DO3: ВКЛ | фактический свет: ВКЛ" in "\n".join(page(ctx, "light", 180).lines)


def test_light_settings_page_has_selectable_rows_and_profile_states(tmp_path):
    ctx, _ = context(tmp_path)
    execute_command(ctx, "view light settings")
    settings_page = page(ctx, "light-settings", 180)
    text = "\n".join(settings_page.lines)
    assert ctx.view == "light-settings"
    assert {key for key in settings_page.row_keys if key} == {f"light:zone-{index}" for index in range(1, 7)}
    assert "F5: применить только свет" in text
    assert "Проверка черновика: КОРРЕКТЕН" in text
    assert "SPECTRAL_4" in text and "Modbus ID 2 / AO2" in text


def test_none_light_does_not_show_false_brightness(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.set_analog_output(2, 1, 7000)
    execute_command(ctx, "light set zone-1 type NONE")
    execute_command(ctx, "light apply")
    lines = page(ctx, "light", 180).lines
    zone_start = next(index for index, line in enumerate(lines) if line.startswith("zone-1 "))
    zone_end = next(index for index, line in enumerate(lines[zone_start + 1 :], zone_start + 1) if line.startswith("zone-2 "))
    zone_text = "\n".join(lines[zone_start:zone_end])
    assert "Светильник не установлен" in zone_text
    assert "70.0%" not in zone_text


def test_main_page_lists_only_powered_light_tiers(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.set_relay(3, True)
    text = "\n".join(page(ctx, "status", 180).lines)
    light_line = next(line for line in text.splitlines() if "ОСВЕЩЕНИЕ ВКЛ:" in line)
    assert "Стеллаж 1, ярус 1" in light_line
    assert "Стеллаж 1, ярус 2" not in light_line


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


def test_settings_are_grouped_and_sorted_by_russian_labels(tmp_path):
    ctx, _ = context(tmp_path)
    settings_page = page(ctx, "settings", 180)
    text = "\n".join(settings_page.lines)
    for title in (
        "ПОСЛЕДОВАТЕЛЬНЫЕ ПОРТЫ",
        "БАКИ И ПЕРЕКАЧКА",
        "ДАВЛЕНИЕ И ГИДРАВЛИКА",
        "НАСОСЫ — ДЕМОНСТРАЦИОННАЯ ФИЗИЧЕСКАЯ МОДЕЛЬ",
        "ЧАСТОТНИК HP1",
    ):
        assert title in text
    capacity_keys = [
        "bp_capacity_l", "bso1_capacity_l", "bso2_capacity_l", "bo_capacity_l",
    ]
    positions = [settings_page.row_keys.index(key) for key in capacity_keys]
    assert positions == sorted(positions)


def test_settings_show_editable_estimated_failure_time_for_every_pump(tmp_path):
    ctx, _ = context(tmp_path)
    settings_page = page(ctx, "settings", 190)
    expected = {
        "bo-to-bp": "120 с (расчётное)",
        "bso1-to-bp": "120 с (расчётное)",
        "bso2-to-bp": "120 с (расчётное)",
        "hp1": "180 с (расчётное)",
        "hp2": "180 с (расчётное)",
    }
    for equipment_id, value in expected.items():
        key = f"equipment:{equipment_id}:failure_s"
        row = settings_page.row_keys.index(key)
        assert value in settings_page.lines[row]
    execute_command(ctx, "equipment set hp1 failure_s 240")
    updated = page(ctx, "settings", 190)
    row = updated.row_keys.index("equipment:hp1:failure_s")
    assert "240 с (расчётное)" in updated.lines[row]
    assert "-/-" in updated.lines[row]


def test_narrow_pages_are_clipped_without_wrapping(tmp_path):
    ctx, _ = context(tmp_path)
    narrow = page(ctx, "devices", 32)
    assert all("\n" not in line and len(line) <= 32 for line in narrow.lines)
    assert any(line.endswith("...") for line in narrow.lines)
    assert "Русское" in narrow.lines[0]
    light = page(ctx, "light", 42)
    assert all("\n" not in line and len(line) <= 42 for line in light.lines)
    assert len(visible_lines(light, height=8, scroll=1000)) == 8


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
    assert completion_candidates("view light ") == ["settings"]
    assert completion_candidates("light set zone-1 type ") == ["none", "single", "spectral_4"]


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


def test_sensor_page_shows_russian_mapping_signal_and_confirmation(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.settings = ctx.draft = type(ctx.settings)(hardware_mode=True)
    ctx.model.force_sensor("bo-min", True)
    state = SensorRelayState(desired=1, confirmed=1, online=True, last_success_at="2026-10-21T12:00:00+00:00")
    sensor_page = render_page(
        "sensors", ctx.model, ctx.journal, ctx.settings, ctx.draft,
        ctx.saved or ctx.settings, width=140, relay_state=state,
    )
    text = "\n".join(sensor_page.lines)
    assert sensor_page.title == "ДАТЧИКИ УРОВНЯ"
    assert "CH1" in text and "bo-min" in text and "Осмос: минимум" in text
    assert "Сигнал" in text and "Треб." in text and "Подтв." in text
    assert "ПОДКЛЮЧЕНО" in text and "FC01" in text


def test_sensor_pages_show_absolute_threshold_and_capacity_percentage(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.sensors["bo-min"].threshold_l = 75
    sensors = page(ctx, "sensors", 140)
    assert any("75 л/15.0%" in line for line in sensors.lines)
    draft = replace(ctx.draft, bo_min_threshold_l=75)
    settings = render_page(
        "settings", ctx.model, ctx.journal, ctx.settings, draft,
        ctx.saved or ctx.settings, width=160,
    )
    assert any("75 л / 15.0%" in line for line in settings.lines)


def test_equipment_page_separates_board_command_fact_and_internal_damage(tmp_path):
    ctx, _ = context(tmp_path)
    drive = ctx.model.drives["hp1"]
    ctx.model.set_relay(drive.selector_relay, True)
    drive.run_register = True
    drive.health.failure = "jammed"
    drive.health.state = "FAILED"
    text = "\n".join(page(ctx, "equipment", 170).lines)
    assert "hp1" in text and "RUN" in text and "ОТКАЗ" in text
    assert "отдельные аварийные сигналы контроллеру не передаются" in text


def test_sensor_page_reports_no_link_instead_of_stale_relay_value(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.settings = ctx.draft = type(ctx.settings)(hardware_mode=True)
    state = SensorRelayState(desired=1, confirmed=1, online=False, error="нет ответа")
    text = "\n".join(render_page(
        "sensors", ctx.model, ctx.journal, ctx.settings, ctx.draft,
        ctx.saved or ctx.settings, width=140, relay_state=state,
    ).lines)
    assert "НЕТ СВЯЗИ" in text
    bo_row = next(line for line in text.splitlines() if "bo-min" in line)
    assert "НЕТ СВЯЗИ" in bo_row


def test_settings_page_contains_sensor_installation_section(tmp_path):
    ctx, _ = context(tmp_path)
    settings_page = page(ctx, "settings", 160)
    text = "\n".join(settings_page.lines)
    assert "ДАТЧИКИ УРОВНЯ" in text
    assert "МОДУЛЬ РЕЛЕ ДАТЧИКОВ" in text
    assert "контакт: NO" in text
    assert "sensor:bo-min" in settings_page.row_keys


def test_ponics_pages_are_separate_and_keep_fixed_bp_demo_banner(tmp_path):
    ctx, _ = context(tmp_path)
    pages = [page(ctx, name, 180) for name in ("ponics", "ponics-settings", "ponics-registers")]
    for rendered in pages:
        text = "\n".join(rendered.lines)
        assert "Бак: БП (Бульон)" in rendered.title
        assert "ДЕМО: показания рассчитаны имитатором" in rendered.title
        assert "Бак: БП (Бульон)" in text
        assert "ДЕМО: показания рассчитаны имитатором" in text
    assert "Запросы / ответы" in "\n".join(pages[0].lines)
    assert "WEB | PDU" in "\n".join(pages[1].lines)
    assert sum("0x" in line for line in pages[2].lines) >= 42


def test_water_page_shows_independent_composition_for_all_tanks(tmp_path):
    ctx, _ = context(tmp_path)
    text = "\n".join(page(ctx, "water", 160).lines)
    assert all(name in text for name in ("Осмос", "Бульон", "Дренаж 1", "Дренаж 2"))
    assert "EC, мСм/см" in text and "Поглощено" in text


def test_drive_pages_show_verified_rw_configuration_and_internal_failure_state(tmp_path):
    ctx, _ = context(tmp_path)
    assert "do-19" in "\n".join(page(ctx, "drives", 160).lines)
    hp1 = "\n".join(page(ctx, "drive-hp1", 160).lines)
    assert "PB.01" in hp1 and "PH.02" in hp1 and "RAW, RW" in hp1
    assert "РАСЧЁТ ИМИТАТОРА" in hp1 and "не передаётся плате" in hp1
