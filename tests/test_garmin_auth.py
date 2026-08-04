"""The auth boundary every scheduled workflow (sync/autosync/push/coach) sits on:
GARMIN_TOKEN materialization, headless reconnect, and the interactive MFA flow."""

from __future__ import annotations

import base64
import io
import tarfile

import pytest

from paceforge import actions
from paceforge.garmin import client as client_mod
from paceforge.garmin.client import GarminClient


def _blob(members: dict[str, bytes]) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return base64.b64encode(buf.getvalue()).decode()


class TestMaterializeToken:
    def test_existing_token_is_not_overwritten(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "tokens"
        token_dir.mkdir()
        (token_dir / "oauth2_token.json").write_text("fresh")
        monkeypatch.setenv("GARMIN_TOKEN", _blob({"oauth2_token.json": b"stale"}))

        actions._materialize_token(token_dir)

        assert (token_dir / "oauth2_token.json").read_text() == "fresh"

    def test_missing_secret_leaves_dir_absent(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "tokens"
        monkeypatch.delenv("GARMIN_TOKEN", raising=False)

        actions._materialize_token(token_dir)

        assert not token_dir.exists()

    def test_path_traversal_member_is_refused(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "tokens"
        monkeypatch.setenv("GARMIN_TOKEN", _blob({"../escaped.json": b"pwned"}))

        with pytest.raises(tarfile.FilterError):
            actions._materialize_token(token_dir)

        assert not (tmp_path / "escaped.json").exists()


class TestGarminConnect:
    def test_unusable_token_raises_actionable_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PACEFORGE_GARMIN_EMAIL", "a@b.c")
        monkeypatch.setenv("PACEFORGE_GARMIN_TOKEN_DIR", str(tmp_path / "tokens"))
        monkeypatch.delenv("GARMIN_TOKEN", raising=False)
        monkeypatch.setattr(GarminClient, "try_reconnect", classmethod(lambda cls, e, d: None))

        with pytest.raises(RuntimeError, match="paceforge login"):
            actions.garmin_connect()

    def test_secret_is_materialized_before_reconnect(self, tmp_path, monkeypatch):
        token_dir = tmp_path / "tokens"
        monkeypatch.setenv("PACEFORGE_GARMIN_EMAIL", "a@b.c")
        monkeypatch.setenv("PACEFORGE_GARMIN_TOKEN_DIR", str(token_dir))
        monkeypatch.setenv("GARMIN_TOKEN", _blob({"oauth1_token.json": b"tok"}))
        seen: dict = {}

        def fake_reconnect(cls, email, dir_):
            seen["contents"] = sorted(p.name for p in token_dir.iterdir())
            return "client"

        monkeypatch.setattr(GarminClient, "try_reconnect", classmethod(fake_reconnect))

        assert actions.garmin_connect() == "client"
        assert seen["contents"] == ["oauth1_token.json"]


class _FakeGarmin:
    """Stand-in for garminconnect.Garmin — login() returns the scripted result."""

    def __init__(self, result, **kwargs):
        self._result = result
        self.resumed: tuple | None = None
        self.client = self

    def login(self, token_dir):
        return self._result

    def resume_login(self, state, code):
        self.resumed = (state, code)

    def dump(self, path):
        pass


def _patch_garmin(monkeypatch, result):
    made = []

    def factory(*args, **kwargs):
        made.append(_FakeGarmin(result, **kwargs))
        return made[-1]

    monkeypatch.setattr(client_mod, "Garmin", factory)
    return made


class TestLoginAndMfa:
    def test_login_without_mfa_returns_none(self, monkeypatch):
        _patch_garmin(monkeypatch, (None, None))

        assert GarminClient("a@b.c", "pw").login() is None

    def test_login_requiring_mfa_reports_it(self, monkeypatch):
        _patch_garmin(monkeypatch, ({"session": 1}, None))

        assert GarminClient("a@b.c", "pw").login() == "mfa_required"

    def test_complete_mfa_forwards_code_and_session(self, monkeypatch, tmp_path):
        made = _patch_garmin(monkeypatch, ({"session": 1}, None))
        client = GarminClient("a@b.c", "pw", token_dir=str(tmp_path))
        client.login()

        client.complete_mfa("123456")

        assert made[0].resumed == ({"session": 1}, "123456")

    def test_complete_mfa_before_login_is_rejected(self):
        with pytest.raises(RuntimeError, match="Call login\\(\\) first"):
            GarminClient("a@b.c", "pw").complete_mfa("123456")

    def test_lost_mfa_session_asks_for_a_restart(self, monkeypatch, tmp_path):
        made = _patch_garmin(monkeypatch, ({"session": 1}, None))
        client = GarminClient("a@b.c", "pw", token_dir=str(tmp_path))
        client.login()

        def boom(state, code):
            raise AttributeError("no mfa session")

        made[0].resume_login = boom

        with pytest.raises(RuntimeError, match="restart the login"):
            client.complete_mfa("123456")

    def test_login_legacy_truthy_mfa_result(self, monkeypatch):
        _patch_garmin(monkeypatch, ("legacy_token", None))

        client = GarminClient("a@b.c", "pw")
        assert client.login() == "mfa_required"
        assert client._mfa_state == {}

    def test_login_empty_tuple_result_returns_none(self, monkeypatch):
        _patch_garmin(monkeypatch, ())

        assert GarminClient("a@b.c", "pw").login() is None

    def test_login_invalid_credentials_propagates(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("Login failed")

        monkeypatch.setattr(client_mod, "Garmin", boom)

        with pytest.raises(RuntimeError, match="Login failed"):
            GarminClient("a@b.c", "pw").login()

    def test_complete_mfa_invalid_code_propagates(self, monkeypatch, tmp_path):
        made = _patch_garmin(monkeypatch, ({"session": 1}, None))
        client = GarminClient("a@b.c", "pw", token_dir=str(tmp_path))
        client.login()

        def reject(state, code):
            raise RuntimeError("Invalid MFA code")

        made[0].resume_login = reject

        with pytest.raises(RuntimeError, match="Invalid MFA code"):
            client.complete_mfa("000000")

    def test_complete_mfa_token_dump_failure_does_not_fail_mfa(self, monkeypatch, tmp_path):
        made = _patch_garmin(monkeypatch, ({"session": 1}, None))
        client = GarminClient("a@b.c", "pw", token_dir=str(tmp_path))
        client.login()

        def explode(path):
            raise RuntimeError("disk full")

        made[0].dump = explode

        client.complete_mfa("123456")
        assert client._mfa_state is None


class TestTryReconnect:
    def test_valid_tokens_yield_a_connected_client(self, monkeypatch, tmp_path):
        _patch_garmin(monkeypatch, (None, None))

        assert GarminClient.try_reconnect("a@b.c", str(tmp_path)) is not None

    def test_mfa_prompt_counts_as_failure(self, monkeypatch, tmp_path):
        _patch_garmin(monkeypatch, ({"session": 1}, None))

        assert GarminClient.try_reconnect("a@b.c", str(tmp_path)) is None

    def test_expired_tokens_yield_none(self, monkeypatch, tmp_path):
        def factory(*args, **kwargs):
            raise RuntimeError("401")

        monkeypatch.setattr(client_mod, "Garmin", factory)

        assert GarminClient.try_reconnect("a@b.c", str(tmp_path)) is None

    def test_any_exception_returns_none(self, monkeypatch, tmp_path):
        def boom(*args, **kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(client_mod, "Garmin", boom)

        assert GarminClient.try_reconnect("a@b.c", str(tmp_path)) is None


class TestLoginAndMfaInterfacePaths:
    """Secondary branches, guards, and property access that existing tests miss."""

    def test_client_property_raises_when_not_logged_in(self):
        with pytest.raises(RuntimeError, match="Call login\\(\\) first"):
            _ = GarminClient("a@b.c", "pw").client

    def test_prompt_mfa_default_is_input_lambda(self):
        client = GarminClient("a@b.c", "pw")
        assert callable(client._prompt_mfa)

    def test_prompt_mfa_can_be_overridden(self):
        def fake_prompt():
            return "111111"

        client = GarminClient("a@b.c", "pw", prompt_mfa=fake_prompt)
        assert client._prompt_mfa is fake_prompt
        assert client._prompt_mfa() == "111111"

    def test_endpoint_records_success(self):
        client = GarminClient("a@b.c", "pw")
        with client._endpoint("stats"):
            pass
        assert client.endpoint_report["stats"] == {"ok": True}

    def test_endpoint_records_failure(self):
        client = GarminClient("a@b.c", "pw")
        try:
            with client._endpoint("stats"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert client.endpoint_report["stats"] == {"ok": False, "error": "RuntimeError: boom"}
    def test_complete_mfa_skips_dump_when_token_dir_empty(self, monkeypatch):
        """Falsy token_dir skips the dump block entirely."""
        made = _patch_garmin(monkeypatch, ({"session": 1}, None))
        client = GarminClient("a@b.c", "pw", token_dir="")
        client.login()

        # Must not raise; dump block is skipped for empty token_dir
        client.complete_mfa("123456")
        assert client._mfa_state is None
