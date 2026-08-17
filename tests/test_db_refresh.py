from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "db_refresh", Path(__file__).resolve().parent.parent / "scripts" / "db_refresh.py"
)
db_refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(db_refresh)


def test_reset_wipes_athlete_data_without_copying_anything(tmp_path):
    inst = tmp_path / "alice"
    (inst / "data" / "analyses").mkdir(parents=True)
    (inst / "data" / "profile.json").write_text('{"name": "alice"}')
    (inst / "data" / "analyses" / "1.md").write_text("x")

    db_refresh.reset_refreshable(inst, None)

    assert not (inst / "data" / "profile.json").exists()
    assert not (inst / "data" / "analyses").exists()


def test_reset_keeps_shipped_workout_library(tmp_path):
    inst = tmp_path / "alice"
    (inst / "data" / "bike" / "workouts").mkdir(parents=True)
    (inst / "data" / "bike" / "workouts" / "w.zwo").write_text("<workout/>")

    db_refresh.reset_refreshable(inst, None)

    assert (inst / "data" / "bike" / "workouts" / "w.zwo").exists()


def test_reset_places_explicit_plan_only(tmp_path):
    inst = tmp_path / "alice"
    plan = tmp_path / "plan.json"
    plan.write_text('{"weeks": []}')

    db_refresh.reset_refreshable(inst, plan)

    assert (inst / "data" / "plan.json").read_text() == '{"weeks": []}'
