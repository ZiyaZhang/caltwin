"""Tests for TwinStore persistence layer."""

import pytest

from twin_runtime.models import TwinState
from twin_runtime.store import TwinStore


class TestTwinStore:
    def test_save_and_load(self, sample_twin, tmp_store_dir):
        store = TwinStore(tmp_store_dir)
        store.save(sample_twin)

        loaded = store.load(sample_twin.user_id)
        assert loaded.id == sample_twin.id
        assert loaded.state_version == sample_twin.state_version
        assert loaded.shared_decision_core.risk_tolerance == 0.7

    def test_load_specific_version(self, sample_twin, tmp_store_dir):
        store = TwinStore(tmp_store_dir)
        store.save(sample_twin)

        loaded = store.load(sample_twin.user_id, "v001")
        assert loaded.state_version == "v001"

    def test_list_versions(self, sample_twin, tmp_store_dir):
        store = TwinStore(tmp_store_dir)
        store.save(sample_twin)

        versions = store.list_versions(sample_twin.user_id)
        assert versions == ["v001"]

    def test_multiple_versions(self, sample_twin, tmp_store_dir):
        store = TwinStore(tmp_store_dir)
        store.save(sample_twin)

        # Create v002
        v2_data = sample_twin.model_dump()
        v2_data["state_version"] = "v002"
        v2_data["shared_decision_core"]["risk_tolerance"] = 0.8
        v2 = TwinState.model_validate(v2_data)
        store.save(v2)

        versions = store.list_versions(sample_twin.user_id)
        assert versions == ["v001", "v002"]

        current = store.load(sample_twin.user_id)
        assert current.state_version == "v002"
        assert current.shared_decision_core.risk_tolerance == 0.8

    def test_rollback(self, sample_twin, tmp_store_dir):
        store = TwinStore(tmp_store_dir)
        store.save(sample_twin)

        v2_data = sample_twin.model_dump()
        v2_data["state_version"] = "v002"
        v2_data["shared_decision_core"]["risk_tolerance"] = 0.8
        v2 = TwinState.model_validate(v2_data)
        store.save(v2)

        rolled = store.rollback(sample_twin.user_id, "v001")
        assert rolled.state_version == "v001"
        assert rolled.shared_decision_core.risk_tolerance == 0.7

        current = store.load(sample_twin.user_id)
        assert current.state_version == "v001"

    def test_has_current(self, sample_twin, tmp_store_dir):
        store = TwinStore(tmp_store_dir)
        assert not store.has_current(sample_twin.user_id)

        store.save(sample_twin)
        assert store.has_current(sample_twin.user_id)

    def test_load_nonexistent_raises(self, tmp_store_dir):
        store = TwinStore(tmp_store_dir)
        with pytest.raises(FileNotFoundError):
            store.load("nonexistent-user")

    def test_delete_user(self, sample_twin, tmp_store_dir):
        store = TwinStore(tmp_store_dir)
        store.save(sample_twin)
        assert store.has_current(sample_twin.user_id)

        store.delete_user(sample_twin.user_id)
        assert not store.has_current(sample_twin.user_id)
