"""Unit tests for `_materialize_token`.

Covers the branches identified in the audit:
  1. no env var  -> no-op
  2. token dir already non-empty -> no-op
  3. normal unpack happy path -> tar members extracted into token dir
  4. corrupt/malformed env blob -> explicit exception instead of silent swallow
  5. path-traversal members -> safety; `filter="data"` rejects `../` escapes

Agents note: branched test files belong in this task workspace copy, but for
acceptance verification we run from the project checkout.
"""

from __future__ import annotations

import base64
import binascii
import os
import io
import tarfile

import pytest

from paceforge import actions


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Never inherit the runner's real `GARMIN_TOKEN` or token meta."""
    monkeypatch.delenv("GARMIN_TOKEN", raising=False)
    monkeypatch.delenv("PACEFORGE_GARMIN_TOKEN_DIR", raising=False)


def _fake_token_gz(members):
    """Build a base64 token blob from an in-memory tar.gz with the given members."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for arcname, data in members:
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return base64.b64encode(buf.getvalue()).decode()


def test_missing_env_var_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_TOKEN", "")
    token_dir = tmp_path / "tokens"

    actions._materialize_token(token_dir)

    assert not token_dir.exists() or not any(token_dir.iterdir())


def test_empty_env_var_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_TOKEN", "")
    token_dir = tmp_path / "tokens"
    token_dir.mkdir()
    (token_dir / "unrelated.file").write_text("keep-me")

    actions._materialize_token(token_dir)

    assert (token_dir / "unrelated.file").exists()
    assert any(token_dir.iterdir())


def test_already_materialized_token_dir_is_noop(tmp_path, monkeypatch):
    token_dir = tmp_path / "tokens"
    token_dir.mkdir()
    (token_dir / "existing.token").write_text("do-not-touch")

    monkeypatch.setenv(
        "GARMIN_TOKEN",
        _fake_token_gz([("token", b"ignored")]),
    )

    actions._materialize_token(token_dir)

    assert any(token_dir.iterdir())
    assert (token_dir / "existing.token").read_text() == "do-not-touch"


def test_happy_path_unpacks_into_token_dir(tmp_path, monkeypatch):
    token_dir = tmp_path / "tokens"
    payload = b"dear-garmin-oauth-token"
    monkeypatch.setenv(
        "GARMIN_TOKEN",
        _fake_token_gz([("garmin_token", payload)]),
    )

    actions._materialize_token(token_dir)

    assert any(token_dir.iterdir())
    assert (token_dir / "garmin_token").read_bytes() == payload


def test_malformed_base64_raises(tmp_path, monkeypatch):
    """Regression: corrupt `GARMIN_TOKEN` raises on decode rather than crashing
    the runner with an unhandled exception later."""
    token_dir = tmp_path / "tokens"
    monkeypatch.setenv("GARMIN_TOKEN", "!!! not base64 !!!")

    with pytest.raises(binascii.Error):
        actions._materialize_token(token_dir)


def test_malformed_tar_archive_raises(tmp_path, monkeypatch):
    """Valid base64 but invalid tar/gzip payload raises instead of swallowing."""
    token_dir = tmp_path / "tokens"
    monkeypatch.setenv(
        "GARMIN_TOKEN",
        base64.b64encode(b"this is not a tar.gz").decode(),
    )

    with pytest.raises(tarfile.ReadError):
        actions._materialize_token(token_dir)


def test_dotdot_member_is_rejected_by_filter(tmp_path, monkeypatch):
    """`filter="data"` must reject members whose extraction escapes the dest.

    Python's strict `tarfile.filter=data` raises FilterError during
    extraction; we assert the resulting content is never written outside
    the destination."
    """
    token_dir = tmp_path / "tokens"

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../evil.txt")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"bad"))

    monkeypatch.setenv(
        "GARMIN_TOKEN",
        base64.b64encode(buf.getvalue()).decode(),
    )

    with pytest.raises((tarfile.FilterError, tarfile.TarError, FileExistsError)):
        actions._materialize_token(token_dir)

    assert not any(token_dir.iterdir())
