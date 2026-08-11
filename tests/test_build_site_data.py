"""Smoke coverage for scripts/build_site_data.py (previously 0%).

Engine internals are stubbed at the boundary (actions.analyze/fitness); the
script's own wiring — profile gate, file writes, hyrox payload shape — runs
for real against a tmp data dir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_site_data as bsd  # noqa: E402


def test_main_without_profile_is_a_clean_noop(monkeypatch):
    monkeypatch.setattr(bsd.store, "load_profile", lambda: None)

    assert bsd.main() == 0


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "hyrox.json").write_text(json.dumps({"results": []}))
    monkeypatch.setattr(bsd.store, "load_profile", lambda: object())
    monkeypatch.setattr(bsd.actions, "analyze", lambda: {"stub": "analytics"})
    monkeypatch.setattr(bsd.actions, "fitness", lambda: {"stub": "fitness"})
    return tmp_path


def test_main_returns_zero(site):
    assert bsd.main() == 0


def test_main_writes_analytics_json(site):
    bsd.main()

    assert json.loads((site / "data" / "analytics.json").read_text()) == {"stub": "analytics"}


def test_main_writes_fitness_json(site):
    bsd.main()

    assert json.loads((site / "data" / "fitness.json").read_text()) == {"stub": "fitness"}


def test_main_writes_hyrox_analysis_with_empty_results(site):
    bsd.main()

    assert json.loads((site / "data" / "hyrox_analysis.json").read_text())["races"] == []


def test_main_writes_weekly_placeholder(site):
    bsd.main()

    assert json.loads((site / "data" / "weekly.json").read_text()) == {"content": None}


def test_main_keeps_existing_weekly_json(site):
    (site / "data" / "weekly.json").write_text(json.dumps({"content": "real review"}))

    bsd.main()

    assert json.loads((site / "data" / "weekly.json").read_text()) == {"content": "real review"}
