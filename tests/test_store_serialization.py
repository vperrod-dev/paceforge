"""Serialization tests around `store._write`'s intra-process lock."""

from __future__ import annotations

import json
import threading

from paceforge import store


class TestStoreWriteSerialization:
    def test_concurrent_writes_end_in_valid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        target = tmp_path / "x.json"
        payloads = [json.dumps({"owner": owner, "n": n})
                    for owner, n in [("A", 1), ("A", 2), ("B", 1), ("B", 2)]]

        def writer(payload, repeats=40):
            for _ in range(repeats):
                store._write(target, payload)

        threads = [threading.Thread(target=writer, args=(p,)) for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = json.loads(target.read_text())
        assert final["owner"] in ("A", "B")
        assert final["n"] in (1, 2)

    def test_writers_do_not_deadlock_when_fast(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "DATA_DIR", tmp_path)
        target = tmp_path / "fast.json"

        def writer(repeats=20):
            for i in range(repeats):
                store._write(target, json.dumps({"i": i}))

        threads = [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
            assert not t.is_alive(), "deadlock: _write did not complete under contention"
