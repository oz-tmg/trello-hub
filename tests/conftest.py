import pytest

from spwf.config import WorkflowConfig


@pytest.fixture
def config_data():
    return {
        "board": "AbCd1234",
        "prefix": "ws",
        "lists": {
            "doing": "Doing",
            "blocked": "Blocked",
            "review": "Review",
            "done_prefix": "Done — ",
        },
    }


@pytest.fixture
def config(config_data):
    return WorkflowConfig.model_validate(config_data)
