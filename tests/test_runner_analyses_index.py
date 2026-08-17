"""GET /analyses index is cached per file on mtime (scripts/runner.py::analyses_index)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import runner  # noqa: E402
from runner import analyses_index  # noqa: E402


def _write(d: Path, name: str, body: str, mtime: int) -> None:
    p = d / f"{name}.md"
    p.write_text(body)
    os.utime(p, (mtime, mtime))


def test_index_lists_headline_newest_first(tmp_path):
    _write(tmp_path, "1", "# Session summary\nEasy run went well.\n", 100)
    _write(tmp_path, "2", "# Session summary\nTempo felt hard.\n", 200)
    assert [x["headline"] for x in analyses_index(tmp_path)] == ["Tempo felt hard.", "Easy run went well."]


def test_unchanged_file_is_not_reread(tmp_path, monkeypatch):
    _write(tmp_path, "1", "# H\nfirst\n", 100)
    analyses_index(tmp_path)
    monkeypatch.setattr(runner.Path, "read_text", lambda self: (_ for _ in ()).throw(AssertionError("re-read")))
    assert analyses_index(tmp_path)[0]["headline"] == "first"


def test_changed_mtime_refreshes_headline(tmp_path):
    _write(tmp_path, "1", "# H\nfirst\n", 100)
    analyses_index(tmp_path)
    _write(tmp_path, "1", "# H\nsecond\n", 200)
    assert analyses_index(tmp_path)[0]["headline"] == "second"


def test_deleted_file_drops_out_of_index(tmp_path):
    _write(tmp_path, "1", "# H\nfirst\n", 100)
    analyses_index(tmp_path)
    (tmp_path / "1.md").unlink()
    assert analyses_index(tmp_path) == []
