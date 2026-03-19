"""Shared fixtures for tests."""

import json
from pathlib import Path

import pytest

from twin_runtime.domain.models import TwinState

from tests.helpers import FIXTURES_DIR, make_situation_frame, make_twin  # noqa: F401

# Re-export for any modules that import from conftest via pytest's plugin system.
__all__ = ["make_situation_frame", "make_twin"]


@pytest.fixture
def sample_twin_dict():
    path = FIXTURES_DIR / "sample_twin_state.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_twin(sample_twin_dict) -> TwinState:
    return TwinState.model_validate(sample_twin_dict)


@pytest.fixture
def tmp_store_dir(tmp_path):
    return tmp_path / "twin_store"
