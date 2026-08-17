#!/usr/bin/env python3
"""Manual DB-refresh for a PaceForge athlete instance.

Does NOT restart/deploy anything: it only wipes that instance's athlete
data back to the empty state `users.py add` provisions, so the destructive
refresh is an explicit manual step instead of being bundled with deploy-like
actions. Nothing is copied from the main checkout: its `data/` is Victor's
own profile/history (PII), and every athlete's data must only ever be their own.

    scripts/db_refresh.py alice
    scripts/db_refresh.py alice --plan data/plan.json

The script refuses when the instance has data history it is about to
wipe unless --yes is passed, and it never touches code, env files,
systemd units, Caddy routes, or runners.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

HOME = Path.home()
USERS = HOME / "projects" / "paceforge-users"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,20}$")
BAD_NAME = "name must be lowercase letters/digits/dashes, 2-21 chars, e.g. 'alice'"

# Tracked athlete data inside an instance checkout. shipped workout library stays.
REFRESHABLE = (
    "data/profile.json",
    "data/plan.json",
    "data/activities.json",
    "data/rpe.json",
    "data/sync-status.json",
    "data/token-meta.json",
    "data/hyrox.json",
    "data/hyrox_analysis.json",
    "data/fitness.json",
    "data/week-review.md",
    "plan.md",
    "week-review.md",
    "data/analyses",
    "data/bike/rides.json",
    "data/bike/profile.json",
)
KEEP_IN_DATA = ("data/bike/workouts/",)


def instance_root(name: str) -> Path:
    return USERS / name


def tracked_refreshable(name: str) -> list[Path]:
    root = instance_root(name)
    out = []
    for rel in REFRESHABLE:
        if rel.startswith(KEEP_IN_DATA):
            continue
        p = root / rel
        if p.exists():
            out.append(p)
    return out


def reset_refreshable(dest: Path, plan: Path | None) -> None:
    for rel in REFRESHABLE:
        if rel.startswith(KEEP_IN_DATA):
            continue
        d = dest / rel
        if d.is_dir():
            shutil.rmtree(d)
        elif d.exists():
            d.unlink()
        if rel == "data/plan.json" and plan is not None and plan.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan, d)


def cmd_refresh(args: argparse.Namespace) -> None:
    name = args.name
    if not NAME_RE.match(name):
        sys.exit(f"! {BAD_NAME}")
    root = instance_root(name)
    if not root.exists():
        sys.exit(f"! instance {name} does not exist at {root}")

    plan = Path(args.plan).resolve() if args.plan else None
    if plan is not None and not plan.exists():
        sys.exit(f"! plan file not found: {args.plan}")

    tracked = tracked_refreshable(name)
    if tracked and not args.yes:
        print(f"! this will overwrite {len(tracked)} tracked file(s) under {root}/data")
        for p in tracked:
            print(f"   {p.relative_to(root)}")
        sys.exit("re-run with --yes to confirm.")

    reset_refreshable(root, plan)
    print(f"refreshed data for {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="instance name")
    ap.add_argument("--plan", help="optional plan.json path to force onto the instance")
    ap.add_argument("--yes", action="store_true", help="confirm destructive overwrite")
    args = ap.parse_args()
    cmd_refresh(args)


if __name__ == "__main__":
    main()
