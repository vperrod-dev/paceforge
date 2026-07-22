"""runner.py web auth: cookie sessions gate Caddy-forwarded requests, localhost stays open."""

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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402

_SALT = "00" * 16
_CONF = _SALT + "$" + hashlib.scrypt(
    b"open-sesame", salt=bytes.fromhex(_SALT), n=2**14, r=8, p=1).hex()
FWD = {"X-Forwarded-For": "203.0.113.9"}  # marks the request as Caddy-proxied


@pytest.fixture()
def base_url(monkeypatch, tmp_path):
    monkeypatch.setenv("PF_WEB_USER", "victor")
    monkeypatch.setenv("PF_WEB_PASS_SCRYPT", _CONF)
    monkeypatch.setenv("PACEFORGE_GARMIN_EMAIL", "victor@example.com")
    monkeypatch.setattr(runner, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(runner, "_SESSIONS", {})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), runner.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


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


def _login(base_url: str, user: str = "victor", password: str = "open-sesame"):
    return _req(base_url + "/api/auth/login", "POST",
                {"user": user, "password": password}, FWD)


def _session_cookie(base_url: str) -> str:
    _, headers, _ = _login(base_url)
    return headers["Set-Cookie"].split(";")[0]


def test_direct_localhost_request_needs_no_session(base_url):
    code, _, _ = _req(base_url + "/api/runs")  # no X-Forwarded-For: timers, curl
    assert code == 200


def test_forwarded_api_request_without_session_is_401(base_url):
    code, _, _ = _req(base_url + "/api/runs", headers=FWD)
    assert code == 401


def test_forwarded_page_request_without_session_gets_login_page(base_url):
    _, _, body = _req(base_url + "/", headers=FWD)
    assert b"auth/login" in body  # the sign-in form, not the portal


def test_healthz_is_open_without_session(base_url):
    code, _, _ = _req(base_url + "/api/healthz", headers=FWD)
    assert code == 200


def test_valid_login_sets_session_cookie(base_url):
    code, headers, _ = _login(base_url)
    assert (code, headers["Set-Cookie"].startswith("pf_session=")) == (204, True)


def test_garmin_email_is_accepted_as_username(base_url):
    code, _, _ = _login(base_url, user="Victor@Example.com")
    assert code == 204


def test_wrong_password_is_rejected(base_url):
    code, _, _ = _login(base_url, password="wrong")
    assert code == 401


def test_session_cookie_grants_api_access(base_url):
    cookie = _session_cookie(base_url)
    code, _, _ = _req(base_url + "/api/runs", headers={**FWD, "Cookie": cookie})
    assert code == 200


def test_expired_session_is_rejected(base_url):
    cookie = _session_cookie(base_url)
    token = cookie.split("=", 1)[1]
    runner._SESSIONS[token] = time.time() - runner.SESSION_TTL - 1
    code, _, _ = _req(base_url + "/api/runs", headers={**FWD, "Cookie": cookie})
    assert code == 401


def test_forwarded_post_without_session_is_401(base_url):
    code, _, _ = _req(base_url + "/api/run/sync", "POST", {}, FWD)
    assert code == 401


def test_check_login_rejects_when_config_missing(monkeypatch):
    monkeypatch.delenv("PF_WEB_PASS_SCRYPT", raising=False)
    monkeypatch.setenv("PF_WEB_USER", "victor")
    assert runner.check_login("victor", "anything") is False
