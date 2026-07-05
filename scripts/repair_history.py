"""One-shot repair of data/history.jsonl — drop all-null rows, merge duplicate dates.

Usage: .venv/bin/python scripts/repair_history.py
"""

from __future__ import annotations

from paceforge import store

if __name__ == "__main__":
    result = store.repair_history()
    print(f"history.jsonl repaired: kept {result['kept']} rows, dropped {result['dropped']}")
