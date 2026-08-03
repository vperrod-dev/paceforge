"""runner.py web auth: cookie sessions gate the public port; the loopback-only
internal port stays open. Trust is the accepting socket, never a client header."""

from __future__ import annotations

# ruff: noqa: S310, S107  (test-local http://127.0.0.1 URLs; a fake test password)
import hashlib
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402

_SALT = "00" * 16
_CONF = _SALT + "$" + hashlib.scrypt(
    b"open-sesame", salt=bytes.fromhex(_SALT), n=2**14, r=8, p=1).hex()
SPOOF = {"X-Forwarded-For": "203.0.113.9"}  # a header a caller could forge — must not grant trust


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("PF_WEB_USER", "victor")
    monkeypatch.setenv("PF_WEB_PASS_SCRYPT", _CONF)
    monkeypatch.setenv("PACEFORGE_GARMIN_EMAIL", "victor@example.com")
    monkeypatch.setattr(runner, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runner, "_SESSIONS", {})
    public = ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    internal = ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    monkeypatch.setattr(runner, "INTERNAL_PORT", internal.server_address[1])
    for srv in (public, internal):
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield SimpleNamespace(
        public=f"http://127.0.0.1:{public.server_address[1]}",
        internal=f"http://127.0.0.1:{internal.server_address[1]}")
    public.shutdown()
    internal.shutdown()


def _req(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None):
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _login(app, user: str = "victor", password: str = "open-sesame"):
    return _req(app.public + "/api/auth/login", "POST", {"user": user, "password": password})


def _session_cookie(app) -> str:
    _, headers, _ = _login(app)
    return headers["Set-Cookie"].split(";")[0]


def test_internal_port_request_needs_no_session(app):
    code, _, _ = _req(app.internal + "/api/runs")  # timers, curl
    assert code == 200


def test_public_request_without_session_is_401(app):
    code, _, _ = _req(app.public + "/api/runs")
    assert code == 401


def test_spoofed_missing_forwarded_header_on_public_port_stays_401(app):
    # A local process reaching the public port and omitting X-Forwarded-For
    # (the old bypass) is still rejected — trust is the socket, not the header.
    code, _, _ = _req(app.public + "/api/runs", headers={})
    assert code == 401


def test_public_page_request_without_session_gets_login_page(app):
    _, _, body = _req(app.public + "/")
    assert b"auth/login" in body  # the sign-in form, not the portal


def test_healthz_is_open_on_public_port(app):
    code, _, _ = _req(app.public + "/api/healthz")
    assert code == 200


def test_valid_login_sets_session_cookie(app):
    code, headers, _ = _login(app)
    assert (code, headers["Set-Cookie"].startswith("pf_session=")) == (204, True)


def test_garmin_email_is_accepted_as_username(app):
    code, _, _ = _login(app, user="Victor@Example.com")
    assert code == 204


def test_wrong_password_is_rejected(app):
    code, _, _ = _login(app, password="wrong")
    assert code == 401


def test_session_cookie_grants_public_api_access(app):
    cookie = _session_cookie(app)
    code, _, _ = _req(app.public + "/api/runs", headers={"Cookie": cookie})
    assert code == 200


def test_expired_session_is_rejected(app):
    cookie = _session_cookie(app)
    token = cookie.split("=", 1)[1]
    runner._SESSIONS[token] = time.time() - runner.SESSION_TTL - 1
    code, _, _ = _req(app.public + "/api/runs", headers={"Cookie": cookie})
    assert code == 401


def test_public_post_without_session_is_401(app):
    code, _, _ = _req(app.public + "/api/run/sync", "POST", {}, SPOOF)
    assert code == 401


def test_oversized_login_body_is_rejected_not_buffered(app):
    # An unauthenticated caller cannot force an unbounded allocation: a body past
    # the cap is read only up to MAX_BODY, so it parses as invalid → 401.
    big = {"user": "victor", "password": "x" * (runner.MAX_BODY + 1000)}
    code, _, _ = _req(app.public + "/api/auth/login", "POST", big)
    assert code == 401


def test_extra_activities_get_without_session_is_401(app):
    code, _, _ = _req(app.public + "/api/extra_activities")
    assert code == 401


def test_extra_activities_post_without_session_is_401(app):
    code, _, _ = _req(app.public + "/api/extra_activities", "POST", {"items": [{"name": "x"}]})
    assert code == 401


def test_extra_activities_get_with_session_still_works(app):
    cookie = _session_cookie(app)
    code, _, _ = _req(app.public + "/api/extra_activities", headers={"Cookie": cookie})
    assert code == 200


def test_sessions_file_is_not_world_or_group_readable(app):
    _login(app)
    mode = runner.SESSIONS_FILE.stat().st_mode & 0o777
    assert mode == 0o600


def test_check_login_rejects_when_config_missing(monkeypatch):
    monkeypatch.delenv("PF_WEB_PASS_SCRYPT", raising=False)
    monkeypatch.setenv("PF_WEB_USER", "victor")
    assert runner.check_login("victor", "anything") is False


def test_contents_route_blocks_path_traversal(app):
    cookie = _session_cookie(app)  # the /contents/ route is behind the session gate
    url = app.public + "/api/gh/repos/o/r/contents/../../../../../../etc/passwd"
    code, _, _ = _req(url, headers={"Cookie": cookie})
    assert code == 404  # escaping data/ is refused, not served


def test_static_route_blocks_path_traversal(app):
    cookie = _session_cookie(app)  # _static() is only reached once authed
    url = app.public + "/api/../../../../../../etc/passwd"
    code, _, _ = _req(url, headers={"Cookie": cookie})
    assert code == 404  # escaping web/ is refused, not served
