from rtuforge.completion import completion_candidates
from rtuforge.config import OPTION_SPECS
from rtuforge.helptext import COMMAND_HELP


def test_top_level_command_completion():
    assert completion_candidates("co") == ["connect"]


def test_script_name_completion():
    names = ["idd-status", "read-basic"]
    assert completion_candidates("run script ", names) == names
    assert completion_candidates("show script ", names) == names
    assert completion_candidates("delete script ", names) == names


def test_option_completion_comes_from_specs():
    assert set(completion_candidates("set options ")) == {spec.name for spec in OPTION_SPECS}


def test_help_completion_comes_from_registry():
    assert set(completion_candidates("help ")) == set(COMMAND_HELP)
