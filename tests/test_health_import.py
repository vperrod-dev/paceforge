"""Tests for :func:`paceforge.actions.import_health_data` (the /health/import webhook).

Fed by Health Auto Export on iOS, forwarding whatever a Hume (or similar) scale
wrote into Apple Health.
"""

from __future__ import annotations

import pytest

from paceforge import actions, store
from paceforge.models.profile import UserFitnessProfile


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def _hae_payload(*, weight=None, body_fat=None) -> dict:
    metrics = []
    if weight is not None:
        metrics.append({
            "name": "weight_body_mass", "units": "kg",
            "data": [{"date": d, "qty": q} for d, q in weight],
        })
    if body_fat is not None:
        metrics.append({
            "name": "body_fat_percentage", "units": "%",
            "data": [{"date": d, "qty": q} for d, q in body_fat],
        })
    return {"data": {"metrics": metrics}}


class TestImportHealthData:
    def test_raises_without_an_existing_profile(self):
        with pytest.raises(ValueError):
            actions.import_health_data(_hae_payload(weight=[("2026-08-11 07:00:00 +0100", 82.1)]))

    def test_writes_a_weight_point(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hae_payload(weight=[("2026-08-11 07:00:00 +0100", 82.1)]))
        points = store.load_profile().health_data.body_composition.weight_kg
        assert [p.value for p in points] == [82.1]

    def test_updates_the_scalar_weight_kg_to_the_latest_point(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hae_payload(weight=[
            ("2026-08-10 07:00:00 +0100", 82.4),
            ("2026-08-11 07:00:00 +0100", 82.1),
        ]))
        assert store.load_profile().weight_kg == 82.1

    def test_reposting_the_same_date_does_not_duplicate_it(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hae_payload(weight=[("2026-08-11 07:00:00 +0100", 82.1)]))
        actions.import_health_data(_hae_payload(weight=[("2026-08-11 09:00:00 +0100", 82.9)]))
        points = store.load_profile().health_data.body_composition.weight_kg
        assert [p.value for p in points] == [82.1]

    def test_unknown_metric_name_is_ignored(self):
        store.save_profile(UserFitnessProfile())
        result = actions.import_health_data({"data": {"metrics": [
            {"name": "step_count", "units": "count", "data": [{"date": "2026-08-11", "qty": 9000}]},
        ]}})
        assert result["written"] == 0

    def test_body_fat_lands_in_its_own_field(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hae_payload(body_fat=[("2026-08-11 07:00:00 +0100", 18.6)]))
        points = store.load_profile().health_data.body_composition.body_fat_pct
        assert [p.value for p in points] == [18.6]


class TestHealthDataSurvivesAGarminSync:
    def test_a_fresh_garmin_profile_does_not_erase_prior_health_data(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hae_payload(weight=[("2026-08-11 07:00:00 +0100", 82.1)]))

        existing = store.load_profile()
        fresh = UserFitnessProfile(vo2_max=52.5)  # simulates a bare Garmin fetch
        fresh.health_data = existing.health_data  # the carry-forward actions.sync() applies
        store.save_profile(fresh)

        assert store.load_profile().health_data.body_composition.weight_kg[0].value == 82.1
