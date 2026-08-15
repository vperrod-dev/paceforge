"""One-time migration: pull your data out of the old PaceForge SQLite DB into data/*.json.

Get the DB off Azure first (Kudu console / SCM:
  https://paceforge-app.scm.azurewebsites.net  →  /home/data/paceforge.db),
then:

    python scripts/migrate_from_sqlite.py paceforge.db [--email you@example.com]

It refuses to clobber data files that already exist unless --yes is passed.
The old `user_data` JSON blobs are already in our Pydantic schema, so this is a
straight copy + pretty-print. Verify afterwards with `paceforge status`.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# old column → new data file
MAPPING = {
    "profile_json": "profile.json",
    "plan_json": "plan.json",
    "activities_json": "activities.json",
    "hyrox_json": "hyrox.json",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="path to the old paceforge.db")
    ap.add_argument("--email", help="which user to migrate (default: the first user)")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--yes", action="store_true", help="confirm overwriting existing data files")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    if args.email:
        user = con.execute("SELECT id, email FROM users WHERE email=?", (args.email,)).fetchone()
    else:
        user = con.execute("SELECT id, email FROM users ORDER BY id LIMIT 1").fetchone()
    if not user:
        print("No matching user.", file=sys.stderr)
        return 1
    print(f"Migrating user {user['email']} (id={user['id']})")

    ud = con.execute("SELECT * FROM user_data WHERE user_id=?", (user["id"],)).fetchone()
    if not ud:
        print("No user_data row for that user.", file=sys.stderr)
        return 1

    out = Path(args.data_dir)
    out.mkdir(parents=True, exist_ok=True)
    cols = set(ud.keys())
    writes = {fname: ud[col] for col, fname in MAPPING.items() if col in cols and ud[col]}

    existing = [out / fname for fname in writes if (out / fname).exists()]
    if existing and not args.yes:
        print(f"! this will overwrite {len(existing)} existing file(s):", file=sys.stderr)
        for p in existing:
            print(f"   {p}", file=sys.stderr)
        print("re-run with --yes to confirm.", file=sys.stderr)
        return 1

    for fname, raw in writes.items():
        (out / fname).write_text(json.dumps(json.loads(raw), indent=2))
        print(f"  wrote {out / fname}")

    con.close()
    print("Done. Run `paceforge status` to confirm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
