"""Tests for :func:`paceforge.actions.import_health_data` (the /health/import webhook).

Fed by a Shortcuts automation wrapping Health Export Kit's "Export Health
Data" action, forwarding whatever a Hume (or similar) scale wrote into Apple
Health.
"""

from __future__ import annotations

import pytest

from paceforge import actions, store
from paceforge.models.profile import UserFitnessProfile


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)


def _hek_payload(*, weight=None, body_fat=None, bmi=None) -> dict:
    days = {}
    for date, value in (weight or []):
        days.setdefault(date, {})["bodyMass"] = value
    for date, value in (body_fat or []):
        days.setdefault(date, {})["bodyFat"] = value
    for date, value in (bmi or []):
        days.setdefault(date, {})["bmi"] = value
    return {"additional": {"body": {"daily": [
        {"date": d, "values": v} for d, v in days.items()
    ]}}}


class TestImportHealthData:
    def test_raises_without_an_existing_profile(self):
        with pytest.raises(ValueError):
            actions.import_health_data(_hek_payload(weight=[("2026-08-09", 90.1)]))

    def test_writes_a_weight_point(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(weight=[("2026-08-09", 90.1)]))
        points = store.load_profile().health_data.body_composition.weight_kg
        assert [p.value for p in points] == [90.1]

    def test_updates_the_scalar_weight_kg_to_the_latest_point(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(weight=[
            ("2026-08-06", 91.0),
            ("2026-08-09", 90.1),
        ]))
        assert store.load_profile().weight_kg == 90.1

    def test_reposting_the_same_date_does_not_duplicate_it(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(weight=[("2026-08-09", 90.1)]))
        actions.import_health_data(_hek_payload(weight=[("2026-08-09", 89.5)]))
        points = store.load_profile().health_data.body_composition.weight_kg
        assert [p.value for p in points] == [90.1]

    def test_unrelated_export_categories_are_ignored(self):
        store.save_profile(UserFitnessProfile())
        result = actions.import_health_data({
            "additional": {"heart": {"daily": [{"date": "2026-08-09", "values": {"restingHR": 50}}]}},
        })
        assert result["written"] == 0

    def test_body_fat_lands_in_its_own_field(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(body_fat=[("2026-08-09", 15.8)]))
        points = store.load_profile().health_data.body_composition.body_fat_pct
        assert [p.value for p in points] == [15.8]

    def test_bmi_lands_in_its_own_field(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(bmi=[("2026-08-09", 28.1)]))
        points = store.load_profile().health_data.body_composition.bmi
        assert [p.value for p in points] == [28.1]


class TestRejectsBadValues:
    @pytest.mark.parametrize("value", [-70.0, 0.0, 5000.0, float("nan"), float("inf"),
                                       float("-inf"), "abc"])
    def test_out_of_range_or_non_finite_weight_is_not_persisted(self, value):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(weight=[("2026-08-09", value)]))
        assert store.load_profile().health_data.body_composition.weight_kg == []

    def test_bad_value_returns_written_zero(self):
        store.save_profile(UserFitnessProfile())
        result = actions.import_health_data(_hek_payload(weight=[("2026-08-09", float("nan"))]))
        assert result["written"] == 0

    @pytest.mark.parametrize("value", [-1.0, 0.0, 101.0, float("nan")])
    def test_out_of_range_body_fat_is_not_persisted(self, value):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(body_fat=[("2026-08-09", value)]))
        assert store.load_profile().health_data.body_composition.body_fat_pct == []

    @pytest.mark.parametrize("value", [-5.0, 0.0, 250.0, float("inf")])
    def test_out_of_range_bmi_is_not_persisted(self, value):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(bmi=[("2026-08-09", value)]))
        assert store.load_profile().health_data.body_composition.bmi == []

    def test_a_bad_point_does_not_block_a_good_one(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(weight=[
            ("2026-08-08", float("nan")),
            ("2026-08-09", 90.1),
        ]))
        points = store.load_profile().health_data.body_composition.weight_kg
        assert [p.value for p in points] == [90.1]


class TestHealthDataSurvivesAGarminSync:
    def test_a_fresh_garmin_profile_does_not_erase_prior_health_data(self):
        store.save_profile(UserFitnessProfile())
        actions.import_health_data(_hek_payload(weight=[("2026-08-09", 90.1)]))

        existing = store.load_profile()
        fresh = UserFitnessProfile(vo2_max=52.5)  # simulates a bare Garmin fetch
        fresh.health_data = existing.health_data  # the carry-forward actions.sync() applies
        store.save_profile(fresh)

        assert store.load_profile().health_data.body_composition.weight_kg[0].value == 90.1
