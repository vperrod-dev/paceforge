"""A per-user instance never has PACEFORGE_GARMIN_EMAIL in its env — it only ever
learns the address from the portal's "Connect Garmin" form, which the runner
persists to token-meta.json. Every scheduled job depends on that fallback."""

from __future__ import annotations

import json

import pytest

from paceforge import actions, store


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.delenv("PACEFORGE_GARMIN_EMAIL", raising=False)
    return tmp_path


def test_env_wins_over_stored_email(data_dir, monkeypatch):
    store.save_token_meta({"login_date": "2026-07-22", "email": "stored@example.com"})
    monkeypatch.setenv("PACEFORGE_GARMIN_EMAIL", "env@example.com")

    assert actions._garmin_email() == "env@example.com"


def test_falls_back_to_the_portal_login_email(data_dir):
    store.save_token_meta({"login_date": "2026-07-22", "email": "friend@example.com"})

    assert actions._garmin_email() == "friend@example.com"


def test_never_connected_yet_asks_for_the_portal_login(data_dir):
    with pytest.raises(RuntimeError, match="connect Garmin in the portal"):
        actions._garmin_email()


def test_runner_persists_the_email_it_logged_in_with(data_dir):
    """The runner writes token-meta.json itself (scripts/runner.py:_garmin_finish);
    this pins the shape actions._garmin_email() reads back."""
    store.save_token_meta({"login_date": "2026-07-22", "email": "friend@example.com"})

    meta = json.loads((data_dir / "token-meta.json").read_text())

    assert meta["email"] == "friend@example.com"
