"""PaceForge CLI — thin wrapper over :mod:`paceforge.actions`.

    paceforge login                 # one-time Garmin auth → prints GARMIN_TOKEN
    paceforge sync                  # pull Garmin metrics+activities → data/*.json
    paceforge status                # show stored profile + plan summary
    paceforge analyze               # full analytics over the stored profile
    paceforge validate              # check data/plan.json against the rules
    paceforge push [--week N] [--dry-run]   # push a plan week to Garmin
"""

from __future__ import annotations

import argparse
import json
import sys

from paceforge import actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paceforge", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="one-time Garmin login (handles MFA)")
    p_sync = sub.add_parser("sync", help="pull Garmin metrics + activities")
    p_sync.add_argument("--lookback-days", type=int, default=90)
    p_sync.add_argument("--details", type=int, default=40,
                        help="fetch splits for the N most recent activities (0 to skip)")
    p_plan = sub.add_parser("plan", help="scaffold a deterministic baseline plan")
    p_plan.add_argument("--goal", required=True,
                        choices=["5K", "10K", "HALF_MARATHON", "MARATHON", "HYROX"])
    p_plan.add_argument("--date", required=True, help="race date YYYY-MM-DD")
    p_plan.add_argument("--level", default="intermediate",
                        choices=["beginner", "intermediate", "advanced"])
    p_plan.add_argument("--days", default="tuesday,thursday,saturday,sunday",
                        help="comma-separated training days")
    p_plan.add_argument("--long-run-day", default="sunday")
    p_plan.add_argument("--target-time", type=float, default=None, help="goal finish seconds")
    p_plan.add_argument("--recent-race", default=None,
                        help="stated recent race as DIST=SECONDS (e.g. 10K=3150) — "
                             "derives paces ahead of any device metric")
    p_plan.add_argument("--weekly-km", type=float, default=None,
                        help="self-declared current weekly volume (km) — anchors the ramp")
    sub.add_parser("status", help="show stored profile + plan summary")
    sub.add_parser("analyze", help="run analytics over the stored profile")
    sub.add_parser("validate", help="validate data/plan.json")
    sub.add_parser("plan-md", help="regenerate plan.md from data/plan.json")

    p_recal = sub.add_parser("recalibrate", help="shift plan paces by a VDOT delta (future weeks only)")
    p_recal.add_argument("--delta", type=float, required=True, help="VDOT change, e.g. 0.5 or -0.5")
    p_recal.add_argument("--force", action="store_true")

    p_push = sub.add_parser("push", help="push a plan week to Garmin")
    p_push.add_argument("--week", type=int, default=None)
    p_push.add_argument("--dry-run", action="store_true")

    sub.add_parser("autosync",
                   help="reconcile Garmin with the plan: clean stale copies + orphans, "
                        "push current + next 2 weeks")

    p_adapt = sub.add_parser("adapt", help="reflow missed sessions + readiness-gate hard work")
    p_adapt.add_argument("--dry-run", action="store_true")

    sub.add_parser("garmin-delete", help="delete all plan workouts from the Garmin calendar")

    p_gcc = sub.add_parser("garmin-clear-calendar",
                           help="remove ALL scheduled Garmin workouts from today onwards")
    p_gcc.add_argument("--days", type=int, default=400, help="look-ahead window")
    p_gcc.add_argument("--dry-run", action="store_true", help="list without deleting")

    p_cal = sub.add_parser("calendar-edit", help="reschedule/delete one session + sync Garmin")
    p_cal.add_argument("session_id", help="Workout.session_id from plan.json")
    p_cal.add_argument("action", choices=["reschedule", "delete"])
    p_cal.add_argument("--new-date", default=None, help="YYYY-MM-DD (reschedule only)")

    for cmd, help_ in (("hyrox-search", "find your HYROX races (pick-list)"),
                       ("hyrox-import", "import chosen HYROX races with splits")):
        p = sub.add_parser(cmd, help=help_)
        p.add_argument("name", help="athlete surname or full name")
        p.add_argument("--firstname", default="")
        p.add_argument("--gender", default="M", choices=["M", "F"])
        if cmd == "hyrox-import":
            p.add_argument("--urls", default="", help="comma-separated athlete URLs to import")

    p_rpe = sub.add_parser("rpe", help="log a session RPE (1-10) for training load")
    p_rpe.add_argument("rpe", type=int, help="perceived exertion 1-10")
    p_rpe.add_argument("activity_id", type=int, nargs="?", default=None,
                       help="Garmin activity id (omit with --date for unrecorded sessions)")
    p_rpe.add_argument("--date", default=None, help="session date YYYY-MM-DD")
    p_rpe.add_argument("--duration-min", type=float, default=None)
    p_rpe.add_argument("--notes", default="")

    p_link = sub.add_parser("link", help="pin a Garmin activity to a plan workout (sync-proof)")
    p_link.add_argument("activity_id", type=int)
    p_link.add_argument("--session-id", default=None, help="Workout.session_id from plan.json")
    p_link.add_argument("--date", default=None, help="workout date YYYY-MM-DD")

    p_unlink = sub.add_parser("unlink",
                              help="detach an activity from its workout and block re-auto-match")
    p_unlink.add_argument("activity_id", type=int)

    p_brief = sub.add_parser("brief", help="print the morning brief (readiness/sleep/today)")
    p_brief.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    p_brief.add_argument("--telegram", action="store_true",
                         help="emit Telegram-HTML (bold headers, emoji, pace band)")

    sub.add_parser("export-token", help="print current on-disk token as a GARMIN_TOKEN blob")

    sub.add_parser("refresh-token", help="refresh Garmin token with local credentials/regenerate blob")

    p_hp = sub.add_parser("hyrox-import-profile",
                          help="import every race from a hyresult.com athlete profile")
    p_hp.add_argument("slug", help="hyresult athlete slug, e.g. victor-perez-rodriguez")
    p_hp.add_argument("--gender", default="M", choices=["M", "F"])

    args = parser.parse_args(argv)

    try:
        if args.cmd == "login":
            token = actions.login()
            print("\nGarmin login OK. Store this as the GARMIN_TOKEN secret:\n", file=sys.stderr)
            print(token)
            return 0
        if args.cmd == "export-token":
            print(actions.export_token())
            return 0
        if args.cmd == "refresh-token":
            _emit(actions.refresh_token())
            return 0
        if args.cmd == "sync":
            _emit(actions.sync(lookback_days=args.lookback_days, details_limit=args.details))
        elif args.cmd == "plan":
            goal_dict = {
                "goal_type": args.goal,
                "target_date": args.date,
                "experience_level": args.level,
                "training_days": [d.strip() for d in args.days.split(",")],
                "long_run_day": args.long_run_day,
                "target_time_seconds": args.target_time,
                "current_weekly_km": args.weekly_km,
            }
            if args.recent_race and "=" in args.recent_race:
                dist, _, secs = args.recent_race.partition("=")
                goal_dict["recent_race_distance"] = dist.strip()
                goal_dict["recent_race_seconds"] = float(secs)
            _emit(actions.scaffold(goal_dict))
        elif args.cmd == "status":
            _emit(actions.status())
        elif args.cmd == "analyze":
            _emit(actions.analyze())
        elif args.cmd == "validate":
            issues = actions.validate()
            if issues:
                print("INVALID:")
                for i in issues:
                    print(f"  - {i}")
                return 1
            print("valid")
        elif args.cmd == "plan-md":
            actions.plan_md()
            print("plan.md regenerated")
        elif args.cmd == "recalibrate":
            _emit(actions.recalibrate(args.delta, force=args.force))
        elif args.cmd == "push":
            _emit(actions.push(week=args.week, dry_run=args.dry_run))
        elif args.cmd == "autosync":
            _emit(actions.autosync())
        elif args.cmd == "rpe":
            _emit(actions.log_rpe(args.activity_id, args.date, rpe=args.rpe,
                                  duration_min=args.duration_min, notes=args.notes))
        elif args.cmd == "brief":
            print(actions.brief(args.date, fmt="telegram" if args.telegram else "text"))
        elif args.cmd == "link":
            _emit(actions.link_activity(args.activity_id, session_id=args.session_id,
                                        when=args.date))
        elif args.cmd == "unlink":
            _emit(actions.unlink_activity(args.activity_id))
        elif args.cmd == "adapt":
            _emit(actions.adapt(dry_run=args.dry_run))
        elif args.cmd == "garmin-delete":
            _emit(actions.garmin_delete())
        elif args.cmd == "garmin-clear-calendar":
            _emit(actions.garmin_clear_calendar(days_ahead=args.days, dry_run=args.dry_run))
        elif args.cmd == "calendar-edit":
            _emit(actions.calendar_edit(args.session_id, args.action, new_date=args.new_date))
        elif args.cmd == "hyrox-search":
            _emit(actions.hyrox_search(args.name, gender=args.gender, firstname=args.firstname))
        elif args.cmd == "hyrox-import":
            urls = [u.strip() for u in args.urls.split(",") if u.strip()] or None
            _emit(actions.hyrox_import(
                args.name, gender=args.gender, firstname=args.firstname, selected_urls=urls))
        elif args.cmd == "hyrox-import-profile":
            _emit(actions.hyrox_import_profile(args.slug, gender=args.gender))
    except (RuntimeError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _emit(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
