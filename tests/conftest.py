import pytest

from repeat_pump.core.config import Config
from repeat_pump.core.context import RunContext
from tests.fixtures.synthetic import build_world


@pytest.fixture
def world(tmp_path):
    """(cfg_dict, tmp_path) for the synthetic world."""
    _, cfg = build_world(tmp_path)
    return cfg, tmp_path


def make_ctx(cfg_dict) -> RunContext:
    return RunContext(Config.model_validate(cfg_dict))
