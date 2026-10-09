import pytest
import yaml

from spwf.config import ConfigError, load_config
from spwf.state import State


def test_load_config_preserves_list_spacing_and_defaults(tmp_path, config_data):
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.safe_dump(config_data))
    config = load_config(path)
    assert config.allow_done_from_push is True
    assert config.experiment_label == "T: Experiment"
    assert config.lists.reference == "📌 Program & Gates"
    assert config.target_list(State.DONE, month_label="October") == "Done — October"
    assert config.target_list(State.DOING) == "Doing"


@pytest.mark.parametrize("state,expected", [
    (State.DOING, "Doing"), (State.BLOCKED, "Blocked"), (State.REVIEW, "Review"),
])
def test_logical_state_maps_to_configured_name(config, state, expected):
    assert config.target_list(state) == expected


def test_done_does_not_guess_board_month_format(config):
    with pytest.raises(ConfigError, match="current-month"):
        config.target_list(State.DONE)


@pytest.mark.parametrize("field,value", [
    ("board", "not-a-board"),
    ("prefix", "WS"),
    ("prefix", "unknown"),
    ("allow_done_from_push", "false"),
    ("TRELLO_TOKEN", "private-value-do-not-print"),
    ("experiment_label", "  "),
])
def test_invalid_config_is_rejected_without_echoing_values(tmp_path, config_data, field, value):
    config_data[field] = value
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.safe_dump(config_data))
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert str(value) not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("content", [
    "", "[]", "board: [", "board: a\nboard: b\n",
    "!!python/object/apply:os.system ['echo unsafe']",
    "? [unhashable, key]\n: value",
])
def test_invalid_yaml_is_rejected(tmp_path, content):
    path = tmp_path / "workflow.yaml"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_nested_duplicate_keys_rejected(tmp_path, config_data):
    path = tmp_path / "workflow.yaml"
    del config_data["lists"]
    path.write_text(yaml.safe_dump(config_data) + "\nlists:\n  doing: first\n  doing: second\n")
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(path)


def test_distinct_states_cannot_map_to_same_list(tmp_path, config_data):
    config_data["lists"]["review"] = config_data["lists"]["doing"]
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.safe_dump(config_data))
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_config_is_safe(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")
