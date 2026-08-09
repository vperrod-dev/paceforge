"""The /extra_activities read/write pair behind the Calendar's extra sessions.

Only its 401 gating was covered; the write shape and the delete-by-index flow
web/index.html's delExtra() depends on were not.
"""

from __future__ import annotations

# ruff: noqa: S310, F811  (test-local http://127.0.0.1 URLs; imported pytest fixture)
import json

import pytest

from tests.test_runner_auth import _req, _session_cookie, app, runner  # noqa: F401


@pytest.fixture()
def data_dir(monkeypatch, tmp_path):
    """Point the runner at a throwaway checkout — it writes data/ relative to REPO_DIR."""
    monkeypatch.setattr(runner, "REPO_DIR", tmp_path)
    (tmp_path / "data").mkdir()
    return tmp_path / "data"


def _post(app, cookie, items):
    return _req(app.public + "/api/extra_activities", "POST", {"items": items},
                headers={"Cookie": cookie, "Origin": app.public})


def test_post_persists_the_items_as_a_json_list(app, data_dir):
    cookie = _session_cookie(app)
    code, _, _ = _post(app, cookie, [{"name": "HYROX class", "date": "2026-08-05"}])
    assert code == 200
    assert json.loads((data_dir / "extra_activities.json").read_text()) == [
        {"name": "HYROX class", "date": "2026-08-05"}]


def test_post_reports_how_many_items_were_stored(app, data_dir):
    cookie = _session_cookie(app)
    _, _, body = _post(app, cookie, [{"name": "a"}, {"name": "b"}])
    assert json.loads(body)["count"] == 2


def test_get_returns_what_post_stored(app, data_dir):
    cookie = _session_cookie(app)
    _post(app, cookie, [{"name": "swim"}])
    _, _, body = _req(app.public + "/api/extra_activities", headers={"Cookie": cookie})
    assert json.loads(body) == [{"name": "swim"}]


def test_deleting_one_index_leaves_the_others(app, data_dir):
    # delExtra() splices the entry out client-side and posts the remainder back.
    cookie = _session_cookie(app)
    _post(app, cookie, [{"name": "a"}, {"name": "b"}, {"name": "c"}])
    _post(app, cookie, [{"name": "a"}, {"name": "c"}])
    _, _, body = _req(app.public + "/api/extra_activities", headers={"Cookie": cookie})
    assert json.loads(body) == [{"name": "a"}, {"name": "c"}]


def test_post_rejects_a_body_that_is_not_a_list(app, data_dir):
    cookie = _session_cookie(app)
    code, _, _ = _req(app.public + "/api/extra_activities", "POST", {"items": "everything"},
                      headers={"Cookie": cookie, "Origin": app.public})
    assert code == 400


def test_a_missing_file_reads_as_an_empty_list(app, data_dir):
    cookie = _session_cookie(app)
    _, _, body = _req(app.public + "/api/extra_activities", headers={"Cookie": cookie})
    assert json.loads(body) == []
