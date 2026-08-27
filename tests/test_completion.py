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


def test_option_completion_comes_from_specs():
    assert set(completion_candidates("set options ")) == {spec.name for spec in OPTION_SPECS}


def test_option_value_completion_uses_choices():
    assert completion_candidates("set options language ") == ["en", "ru"]
    assert completion_candidates("set options parity e") == ["E"]


def test_help_completion_comes_from_registry():
    assert set(completion_candidates("help ")) == set(help_topics())


def test_history_clear_completion():
    assert completion_candidates("history ") == ["clear"]
    assert completion_candidates("history c") == ["clear"]


def test_send_flag_completion():
    assert "--decode" in completion_candidates("send ")
    assert completion_candidates("send --d") == ["--decode"]
