from rtuforge.completion import completion_candidates
from rtuforge.config import OPTION_SPECS
from rtuforge.i18n import help_topics


def test_top_level_command_completion():
    assert completion_candidates("co") == ["connect"]


def test_script_name_completion():
    names = ["idd-status", "read-basic"]
    assert completion_candidates("run script ", names) == names
    assert completion_candidates("show script ", names) == names
    assert completion_candidates("delete script ", names) == names
    assert completion_candidates("record script ", names) == names


def test_show_record_completion():
    assert completion_candidates("show ") == ["record", "script"]
    assert completion_candidates("show r") == ["record"]


def test_option_completion_comes_from_specs():
    assert set(completion_candidates("set options ")) == {spec.name for spec in OPTION_SPECS}


def test_option_value_completion_uses_choices():
    assert completion_candidates("set options language ") == ["en", "ru"]
    assert completion_candidates("set options parity e") == ["E"]


def test_help_completion_comes_from_registry():
    expected = set(help_topics()) | {"record"}
    assert set(completion_candidates("help ")) == expected


def test_history_clear_completion():
    assert completion_candidates("history ") == ["clear"]
    assert completion_candidates("history c") == ["clear"]


def test_send_flag_completion():
    assert "--decode" in completion_candidates("send ")
    assert completion_candidates("send --d") == ["--decode"]


def test_scan_completion():
    assert "scan" in completion_candidates("sc")
    assert set(completion_candidates("scan ")) == {"--timeout", "--function", "--address"}
    assert completion_candidates("scan 1 32 --function ") == ["01", "02", "03", "04"]


def test_run_script_flag_completion():
    choices = completion_candidates("run script idd-status ", ["idd-status"])
    assert set(choices) == {"--decode", "--raw", "-d", "-r"}


def test_record_completion():
    assert completion_candidates("record ") == ["cancel", "script", "start", "status", "stop"]
    assert completion_candidates("record start ") == ["all", "rx"]
    assert completion_candidates("record stop ") == ["buffer", "clipboard", "file"]


def test_record_script_completion():
    names = ["idd-status"]
    assert completion_candidates("record script ", names) == names
    assert completion_candidates("record script idd-status ", names) == ["all", "rx"]
    assert completion_candidates("record script idd-status rx ", names) == ["buffer", "clipboard", "file"]
    flags = completion_candidates("record script idd-status rx file capture.txt ", names)
    assert set(flags) == {"--clean", "--decode", "--raw", "-c", "-d", "-r"}
