from pathlib import Path
from dataclasses import replace

import pytest
from rich.console import Console
from rich.cells import cell_len

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
        help_query=ctx.help_query, relay_state=ctx.sensor_relay_state,
    )


def test_required_views_have_separate_content(tmp_path):
    ctx, _ = context(tmp_path)
    status = "\n".join(page(ctx, "status").lines)
    help_text = "\n".join(page(ctx, "help").lines)
    settings = "\n".join(page(ctx, "settings").lines)
    devices = "\n".join(page(ctx, "devices").lines)
    ports = "\n".join(page(ctx, "ports").lines)

    assert set(VIEW_NAMES) >= {"status", "devices", "ports", "settings", "help", "log"}
    assert "БАКИ" in status and "АВАРИИ" in status and "СВЯЗЬ" in status
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


def test_main_page_lists_all_light_tiers_and_marks_power(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.set_relay(3, True)
    text = "\n".join(page(ctx, "status", 180).lines)
    rack_line = next(line for line in text.splitlines() if "Стеллаж 1:" in line)
    assert "Я1 ВКЛ" in rack_line
    assert "Я2 ВЫКЛ" in rack_line and "Я3 ВЫКЛ" in rack_line


@pytest.mark.parametrize("width", [50, 59, 60, 79, 80, 109, 110, 120, 160])
def test_status_layout_respects_terminal_cells_at_required_widths(tmp_path, width):
    ctx, _ = context(tmp_path)
    rendered = page(ctx, "status", width)
    expected_mode = "triple" if width >= 150 else ("double" if width >= 110 else "single")
    assert rendered.layout_mode == expected_mode
    assert all(cell_len(line) <= width for line in rendered.lines)
    text = "\n".join(rendered.lines)
    assert text.count("MIN ") == 4 and text.count("MAX ") == 4
    for pump in ("БО→БП", "БСО1→БП", "БСО2→БП", "HP1", "HP2"):
        assert pump in text
    for heading in (
        "БАКИ", "ДАТЧИКИ УРОВНЯ", "НАСОСЫ", "PONICPILOT · БП",
        "ЧАСТОТНИКИ", "ГИДРАВЛИКА", "КЛАПАНЫ И ВЫХОДЫ",
        "ОСВЕЩЕНИЕ", "АВАРИИ", "СВЯЗЬ",
    ):
        assert heading in text


def test_status_exact_column_boundary_and_120_geometry(tmp_path):
    ctx, _ = context(tmp_path)
    assert page(ctx, "status", 109).layout_mode == "single"
    at_110 = page(ctx, "status", 110)
    assert at_110.layout_mode == "double"
    at_120 = page(ctx, "status", 120)
    assert at_120.column_widths == (64, 51)
    assert " │ " in at_120.lines[0]
    assert at_120.lines[0].split(" │ ", 1)[1].lstrip().startswith("PONICPILOT · БП")
    assert all(cell_len(line) == 120 for line in at_120.lines)
    assert page(ctx, "status", 149).layout_mode == "double"
    at_150 = page(ctx, "status", 150)
    assert at_150.layout_mode == "triple"
    assert at_150.column_widths == (59, 44, 39)
    assert at_150.lines[0].split(" │ ", 2)[2].lstrip().startswith("НАПОЛНЕНИЕ")
    assert all(cell_len(line) == 150 for line in at_150.lines)


def test_status_third_column_uses_one_line_horizontal_gauges_and_live_sensor_marks(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.set_tank_level("bo", 450)
    rendered = page(ctx, "status", 160)
    assert rendered.layout_mode == "triple"
    gauge_line = next(
        line for line in rendered.styled_lines or []
        if "БО   [" in "".join(text for _style, text in line)
    )
    gauge_text = "".join(text for _style, text in gauge_line)
    assert "[" in gauge_text and "]" in gauge_text
    assert "m:ВКЛ" in gauge_text and "M:ВКЛ" in gauge_text
    assert ("sensor_on", "m") in gauge_line
    assert ("sensor_on", "M") in gauge_line
    assert gauge_line.count(("sensor_on", "ВКЛ ")) == 2

    ctx.model.force_sensor("bo-min", False)
    updated = page(ctx, "status", 160)
    updated_line = next(
        line for line in updated.styled_lines or []
        if "БО   [" in "".join(text for _style, text in line)
    )
    updated_text = "".join(text for _style, text in updated_line)
    assert "m:ВЫКЛ M:ВКЛ" in updated_text
    assert gauge_text.index("M:") == updated_text.index("M:")
    assert ("inactive", "ВЫКЛ") in updated_line
    assert ("sensor_on", "ВКЛ ") in updated_line


def test_status_single_column_order_is_stable(tmp_path):
    ctx, _ = context(tmp_path)
    expected = (
        "БАКИ", "ДАТЧИКИ УРОВНЯ", "НАСОСЫ", "PONICPILOT · БП",
        "ЧАСТОТНИКИ", "ГИДРАВЛИКА", "КЛАПАНЫ И ВЫХОДЫ",
        "ОСВЕЩЕНИЕ", "АВАРИИ", "СВЯЗЬ",
    )
    before = "\n".join(page(ctx, "status", 80).lines)
    ctx.model.tanks["bo"].volume_l = 10
    ctx.model.drives["hp1"].actual_hz = 42
    after = "\n".join(page(ctx, "status", 80).lines)
    assert [before.index(item) for item in expected] == sorted(before.index(item) for item in expected)
    assert [after.index(item) for item in expected] == sorted(after.index(item) for item in expected)


def test_status_semantic_colours_follow_fact_not_only_commands(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.model.set_relay(22, True)
    ctx.model.set_relay(ctx.model.pumps["bo-to-bp"].relay, True)
    pump = ctx.model.pumps["bo-to-bp"]
    pump.actual_flow_lpm = 4.0
    drive = ctx.model.drives["hp1"]
    drive.actual_hz = 0.0
    drive.fault = 10
    rendered = page(ctx, "status", 120)
    fragments = [fragment for line in rendered.styled_lines or [] for fragment in line]
    assert ("sensor_on", "ВКЛ ") in fragments
    assert ("output_on", "ВКЛ ") in fragments
    assert ("running", "РАБОТАЕТ") in fragments
    hp1_lines = [
        line for line in rendered.styled_lines or []
        if "HP1" in "".join(text for _style, text in line)
    ]
    assert hp1_lines
    assert not any(style == "running" for line in hp1_lines for style, _text in line)
    assert any(style == "fault" for line in hp1_lines for style, _text in line)
    assert all("\x1b" not in line for line in rendered.lines)


def _status_line(rendered, needle):
    return next(
        line for line in rendered.styled_lines or []
        if needle in "".join(text for _style, text in line)
    )


def _pump_block(rendered, name):
    styled = rendered.styled_lines or []
    start = next(
        index for index, line in enumerate(styled)
        if "".join(text for _style, text in line).lstrip().startswith(name)
        and "CMD" in "".join(text for _style, text in line)
    )
    end = next(
        (
            index for index in range(start + 1, len(styled))
            if " CMD " in "".join(text for _style, text in styled[index])
        ),
        len(styled),
    )
    return styled[start:end]


def test_status_transfer_pump_separates_command_motor_and_flow(tmp_path):
    ctx, _ = context(tmp_path)
    pump = ctx.model.pumps["bo-to-bp"]
    ctx.model.set_relay(pump.relay, True)
    pump.actual_flow_lpm = 3.5
    rendered = page(ctx, "status", 80)
    block = _pump_block(rendered, "БО→БП")
    command_line, flow_line = block[:2]
    assert ("output_on", "ВКЛ ") in command_line
    assert ("running", "РАБОТАЕТ") in command_line
    assert ("demo", " (МОДЕЛЬ)") in command_line
    assert ("ok", "ЕСТЬ 3.50 л/мин") in flow_line


def test_status_dry_running_motor_stays_green_without_flow(tmp_path):
    ctx, _ = context(tmp_path)
    pump = ctx.model.pumps["bo-to-bp"]
    ctx.model.set_relay(pump.relay, True)
    pump.actual_flow_lpm = 0.0
    pump.health.dry_running = True
    rendered = page(ctx, "status", 80)
    block = _pump_block(rendered, "БО→БП")
    command_line, state_line = block[:2]
    assert ("running", "РАБОТАЕТ") in command_line
    assert ("warning", "НЕТ") in state_line
    assert ("fault", "ДА") in state_line


@pytest.mark.parametrize(
    ("failure", "label"),
    [
        ("loss_of_prime", "ОТКАЗ ПОТЕРЯ ЗАЛИВКИ"),
        ("impeller_damage", "ОТКАЗ ПОВРЕЖДЕНО КОЛЕСО"),
    ],
)
def test_status_nonblocking_damage_does_not_fake_motor_stop(tmp_path, failure, label):
    ctx, _ = context(tmp_path)
    pump = ctx.model.pumps["bo-to-bp"]
    ctx.model.set_relay(pump.relay, True)
    pump.health.failure = failure
    rendered = page(ctx, "status", 80)
    block = _pump_block(rendered, "БО→БП")
    assert ("running", "РАБОТАЕТ") in block[0]
    assert any(("fault", label.removeprefix("ОТКАЗ ")) in line for line in block)


def test_status_jammed_transfer_motor_is_stopped(tmp_path):
    ctx, _ = context(tmp_path)
    pump = ctx.model.pumps["bso1-to-bp"]
    ctx.model.set_relay(pump.relay, True)
    pump.health.failure = "jammed"
    rendered = page(ctx, "status", 80)
    command_line = _pump_block(rendered, "БСО1→БП")[0]
    assert ("output_on", "ВКЛ ") in command_line
    assert ("inactive", "СТОП") in command_line
    assert any(
        ("fault", "ЗАКЛИНИВАНИЕ") in line
        for line in _pump_block(rendered, "БСО1→БП")
    )


def test_status_vfd_trip_keeps_board_run_but_stops_motor_and_flow(tmp_path):
    ctx, _ = context(tmp_path)
    drive = ctx.model.drives["hp1"]
    drive.configuration[102] = 1
    ctx.model.set_relay(drive.selector_relay, True)
    ctx.model.set_relay(drive.run_relay, True)
    drive.actual_hz = 0.0
    drive.fault = 10
    assert ctx.model.equipment_commanded("hp1")
    rendered = page(ctx, "status", 80)
    block = _pump_block(rendered, "HP1")
    command_line = block[0]
    assert ("output_on", "ВКЛ ") in command_line
    assert ("inactive", "СТОП") in command_line
    assert any(("inactive", "НЕТ") in line for line in block)
    assert any(("fault", "IDD 10") in line for line in block)


def test_status_hp_rotation_does_not_depend_on_hydraulic_factor(tmp_path):
    ctx, _ = context(tmp_path)
    drive = ctx.model.drives["hp1"]
    drive.actual_hz = 42.0
    drive.health.failure = "dry_run_wear"
    drive.health.damage = 1.0
    assert drive.hydraulic_factor == 0.0
    rendered = page(ctx, "status", 80)
    assert ("running", "РАБОТАЕТ 42.0 Гц") in _pump_block(rendered, "HP1")[0]


def test_status_hp_flow_is_not_invented_when_motor_rotates(tmp_path):
    ctx, _ = context(tmp_path)
    drive = ctx.model.drives["hp1"]
    drive.actual_hz = 42.0
    rendered = page(ctx, "status", 80)
    block = _pump_block(rendered, "HP1")
    assert any(("warning", "НЕ ОПРЕДЕЛЕНА") in line for line in block)


@pytest.mark.parametrize("width", [50, 59, 60, 80, 109, 110, 120, 160])
def test_status_important_pump_states_never_use_ellipsis(tmp_path, width):
    ctx, _ = context(tmp_path)
    transfer = ctx.model.pumps["bo-to-bp"]
    ctx.model.set_relay(transfer.relay, True)
    transfer.health.dry_running = True
    transfer.actual_flow_lpm = 0.0
    damaged = ctx.model.pumps["bso2-to-bp"]
    ctx.model.set_relay(damaged.relay, True)
    damaged.health.failure = "impeller_damage"
    drive = ctx.model.drives["hp1"]
    drive.configuration[102] = 1
    ctx.model.set_relay(drive.selector_relay, True)
    ctx.model.set_relay(drive.run_relay, True)
    drive.fault = 10
    rendered = page(ctx, "status", width)
    left_lines = [line.split(" │ ", 1)[0].strip() for line in rendered.lines]
    start = left_lines.index("НАСОСЫ")
    end = left_lines.index("КЛАПАНЫ И ВЫХОДЫ")
    pump_text = "\n".join(left_lines[start:end])
    assert "..." not in pump_text
    for state in ("ВКЛ", "ВЫКЛ", "РАБОТАЕТ", "СТОП", "СУХОЙ ХОД", "АВАРИЯ", "ОТКАЗ"):
        assert state in pump_text


def test_status_output_columns_do_not_shift_between_on_and_off(tmp_path):
    ctx, _ = context(tmp_path)
    before = _status_line(page(ctx, "status", 80), "Наполнение")
    before_text = "".join(text for _style, text in before)
    ctx.model.set_relay(22, True)
    after = _status_line(page(ctx, "status", 80), "Наполнение")
    after_text = "".join(text for _style, text in after)
    assert ("inactive", "ВЫКЛ") in before
    assert ("output_on", "ВКЛ ") in after
    assert cell_len(before_text) == cell_len(after_text)
    assert before_text.index("Осмос") == after_text.index("Осмос")
    assert before_text.index("|") == after_text.index("|")


@pytest.mark.parametrize("width", [50, 80, 120, 160])
def test_status_level_sensors_use_two_fixed_columns(tmp_path, width):
    ctx, _ = context(tmp_path)
    rendered = page(ctx, "status", width)

    def left_text(line):
        return line.split(" │ ", 1)[0][1:] if rendered.layout_mode != "single" else line

    rows = [
        left_text(line) for line in rendered.lines
        if any(left_text(line).startswith(f"{name:<4} MIN ") for name in ("БО", "БП", "БСО1", "БСО2"))
    ]
    assert len(rows) == 4
    assert len({row.index("MIN") for row in rows}) == 1
    assert len({row.index("|") for row in rows}) == 1
    assert len({row.index("MAX") for row in rows}) == 1
    assert len({row.index(" л") for row in rows}) == 1
    assert len({row.rindex(" л") for row in rows}) == 1

    before = rows[0]
    ctx.model.force_sensor("bo-min", False)
    ctx.model.force_sensor("bo-max", True)
    changed = page(ctx, "status", width)
    changed_row = next(
        left_text(line) for line in changed.lines
        if left_text(line).startswith("БО   MIN ")
    )
    assert before.index("|") == changed_row.index("|")
    assert before.index("MAX") == changed_row.index("MAX")


@pytest.mark.parametrize("width", [50, 80, 110, 120, 160])
def test_status_pump_fields_are_aligned_for_different_state_lengths(tmp_path, width):
    ctx, _ = context(tmp_path)
    before = page(ctx, "status", width)
    pump = ctx.model.pumps["bo-to-bp"]
    ctx.model.set_relay(pump.relay, True)
    pump.actual_flow_lpm = 3.5
    after = page(ctx, "status", width)

    def plain_block(rendered, name):
        lines = [
            (line.split(" │ ", 1)[0][1:].rstrip() if rendered.layout_mode == "double" else line)
            for line in rendered.lines
        ]
        start = next(
            index for index, line in enumerate(lines)
            if line.lstrip().startswith(name) and "CMD" in line
        )
        end = next(
            (index for index in range(start + 1, len(lines)) if " CMD " in lines[index]),
            len(lines),
        )
        return lines[start:end]

    before_blocks = [plain_block(before, name) for name in ("БО→БП", "БСО1→БП", "БСО2→БП", "HP1", "HP2")]
    after_block = plain_block(after, "БО→БП")
    assert len({line[0].index("CMD") for line in before_blocks}) == 1
    assert len({line[0].index("МОТОР") for line in before_blocks}) == 1
    assert len({line[1].index("ПОДАЧА") for line in before_blocks}) == 1
    assert len({line[1].index("СУХОЙ ХОД") for line in before_blocks}) == 1
    assert len({line[1].index("ОТКАЗ") for line in before_blocks}) == 1
    assert all(line[0].index("CMD") == line[1].index("ПОДАЧА") for line in before_blocks)
    assert before_blocks[0][0].index("МОТОР") == after_block[0].index("МОТОР")
    assert before_blocks[0][1].index("СУХОЙ ХОД") == after_block[1].index("СУХОЙ ХОД")
    assert before_blocks[0][1].index("ОТКАЗ") == after_block[1].index("ОТКАЗ")


def test_status_relay_confirmation_mismatch_and_offline_are_visible(tmp_path):
    ctx, _ = context(tmp_path)
    ctx.settings = ctx.draft = replace(ctx.settings, hardware_mode=True)
    ctx.sensor_relay_state = SensorRelayState(desired=1, confirmed=0, online=True)
    mismatch = page(ctx, "status", 120)
    mismatch_text = "\n".join(mismatch.lines)
    assert "≠ ТРЕБ." in mismatch_text and "РАСХОЖДЕНИЕ" in mismatch_text
    assert any(
        style == "warning" and "ТРЕБ" in text
        for line in mismatch.styled_lines or [] for style, text in line
    )
    ctx.sensor_relay_state = SensorRelayState(desired=1, confirmed=None, online=False, error="нет ответа")
    offline = page(ctx, "status", 120)
    assert "НЕТ СВЯЗИ" in "\n".join(offline.lines)
    assert any(
        style == "warning" and text == "НЕТ СВЯЗИ"
        for line in offline.styled_lines or [] for style, text in line
    )


@pytest.mark.parametrize("width", [50, 59, 60, 80, 109, 110, 120, 160])
def test_status_all_relay_no_link_states_are_complete_at_supported_widths(tmp_path, width):
    ctx, _ = context(tmp_path)
    ctx.settings = ctx.draft = replace(ctx.settings, hardware_mode=True)
    ctx.sensor_relay_state = SensorRelayState(
        desired=0, confirmed=None, online=False, error="нет ответа",
    )
    rendered = page(ctx, "status", width)
    left_lines = [line.split(" │ ", 1)[0].strip() for line in rendered.lines]
    start = left_lines.index("ДАТЧИКИ УРОВНЯ")
    end = left_lines.index("НАСОСЫ")
    sensor_text = "\n".join(left_lines[start:end])
    assert sensor_text.count("НЕТ СВЯЗИ") == 8
    assert all("..." not in line for line in left_lines[start:end] if "НЕТ СВЯЗИ" in line)
    for channel in range(1, 9):
        assert f"CH{channel} " in sensor_text


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
    assert "PB.01" in hp1 and "PH.02" in hp1 and "Значение" in hp1
    assert "RS485" in hp1 and "RTU 8N1" in hp1 and "9600 бит/с" in hp1
    assert "29.0 Гц" in hp1 and "включена" in hp1
    assert "РАСЧЁТ ИМИТАТОРА" in hp1 and "не передаётся плате" in hp1

    settings_page = page(ctx, "settings", 180)
    pb01_row = settings_page.row_keys.index("hp1_pb01")
    ph01_row = settings_page.row_keys.index("hp1_ph01")
    assert "5 — RS485" in settings_page.lines[pb01_row]
    assert "3 — RTU 8N1" in settings_page.lines[ph01_row]
