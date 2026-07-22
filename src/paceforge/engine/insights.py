"""Daily actionable insights — transparent rules over the Fitness 2.0 metrics.

Every rule cites published thresholds (Friel TSB bands, Gabbett ACWR, Foster
monotony, HRV-guided-training SWC, Whoop/Garmin readiness zones) rather than an
opaque score: the athlete should always be able to see WHY today is green or red.
Output feeds fitness.json["insights"] and the portal's "Do this" panel.
"""

from __future__ import annotations

from datetime import datetime, timedelta

SEV_ORDER = {"red": 0, "amber": 1, "green": 2, "info": 3}


def _ins(severity: str, area: str, title: str, advice: str, evidence: str) -> dict:
    return {"severity": severity, "area": area, "title": title,
            "advice": advice, "evidence": evidence}


def _tsb_rules(load: dict) -> list[dict]:
    pmc = load.get("ctl_atl_tsb") or {}
    tsb = pmc.get("tsb")
    if tsb is None:
        return []
    if tsb < -30:
        return [_ins("red", "load", "Form deeply negative",
                     "Cut volume now — take 2–3 easy days before any quality.",
                     f"TSB {tsb:.0f}; below −30 is Friel's high-risk zone.")]
    if tsb > 25:
        return [_ins("amber", "load", "Detraining territory",
                     "You are very fresh — add load this week or fitness starts leaking.",
                     f"TSB {tsb:.0f}; above +25 CTL decays faster than it builds.")]
    if -30 <= tsb <= -5:
        return [_ins("green", "load", "Productive training zone",
                     "Ideal window for building — keep the plan's quality sessions.",
                     f"TSB {tsb:.0f}; −5…−30 is the optimal-training band.")]
    return []


def _acwr_rules(load: dict) -> list[dict]:
    acwr = load.get("acwr") or {}
    ratio = acwr.get("acwr")
    if ratio is None:
        return []
    if ratio > 1.5:
        return [_ins("red", "load", "Load spike",
                     "This week is far above your norm — drop one session or trim distances.",
                     f"Acute:chronic {ratio:.2f}; >1.5 carries 2–4× injury risk next week.")]
    if ratio < 0.8:
        return [_ins("amber", "load", "Training below your base",
                     "Room to add — you are loading well under what your body is adapted to.",
                     f"Acute:chronic {ratio:.2f}; the 0.8–1.3 sweet spot builds safely.")]
    return []


def _monotony_rules(load: dict) -> list[dict]:
    ms = load.get("monotony_strain") or {}
    mono = ms.get("monotony")
    if mono is not None and (mono > 2.0 or ms.get("concerning")):
        return [_ins("amber", "load", "Training too samey",
                     "Polarise: make hard days harder and easy days genuinely easy.",
                     f"Monotony {mono:.1f}; Foster flags >2.0 as an overtraining precursor.")]
    return []


def _hrv_rules(load: dict) -> list[dict]:
    hrv = load.get("hrv") or {}
    if hrv.get("status") == "below":
        return [_ins("red", "recovery", "HRV below your normal range",
                     "Postpone quality until HRV is back in range — easy running only.",
                     "7-day HRV under your personal band; HRV-guided athletes gain ~8% more "
                     "by holding intensity on these days.")]
    return []


def _sleep_rules(load: dict, profile: dict) -> list[dict]:
    out: list[dict] = []
    sleep = load.get("sleep") or {}
    debt = sleep.get("sleep_debt_hours")
    dur = profile.get("sleep_duration_seconds")
    if debt is not None and debt > 3:
        nightly = min(60, int(debt * 60 / 14) + 15)
        out.append(_ins("amber" if debt < 10 else "red", "sleep", "Sleep debt building",
                        f"Go to bed ~{nightly} min earlier for the next two weeks.",
                        f"{debt:.0f} h of 14-day sleep debt; last night "
                        f"{dur / 3600:.1f} h." if dur else f"{debt:.0f} h of 14-day sleep debt."))
    arch = sleep.get("architecture") or {}
    deep = arch.get("deep_pct")
    if deep is not None and deep < 13:
        out.append(_ins("amber", "sleep", "Low deep sleep",
                        "Cool room, no alcohol, no screens late — deep sleep drives physical "
                        "repair.", f"Deep sleep {deep:.0f}%; 13–23% is the restorative band."))
    return out


def _body_battery_rules(profile: dict) -> list[dict]:
    bb = profile.get("body_battery_current")
    if bb is None:
        return []
    if bb < 30:
        return [_ins("red", "recovery", "Body Battery critically low",
                     "Recovery failed overnight — make today easy or off, whatever the plan says.",
                     f"Body Battery {bb}; a morning under 30 means charge never happened.")]
    if bb < 40:
        return [_ins("amber", "recovery", "Low charge for quality work",
                     "If today has intensity, swap it with your next easy day.",
                     f"Body Battery {bb}; under 40 quality sessions underperform.")]
    return []


def _stress_rhr_rules(load: dict) -> list[dict]:
    out: list[dict] = []
    rhr = load.get("resting_hr_trend") or {}
    if rhr.get("elevated"):
        out.append(_ins("amber", "recovery", "Resting HR elevated",
                        "Treat as an early warning — hydrate, sleep, keep today conversational.",
                        f"RHR {rhr.get('latest')} vs baseline {rhr.get('baseline')} bpm."))
    stress = load.get("stress_trend") or {}
    if stress.get("elevated"):
        out.append(_ins("amber", "recovery", "Stress running high",
                        "High all-day stress blunts adaptation — protect easy days this week.",
                        f"Daily stress {stress.get('latest_avg')} vs typical "
                        f"{stress.get('mean_avg')}."))
    return out


def _illness_rules(load: dict) -> list[dict]:
    iw = load.get("illness_watch") or {}
    if iw.get("level") == "alert":
        sig = ", ".join(s.replace("_", " ") for s in iw.get("signals", []))
        return [_ins("red", "recovery", "Illness signals",
                     "Skip intensity entirely until overnight signals clear.", sig or
                     "multiple overnight markers off baseline")]
    return []


def _distribution_rules(running: dict) -> list[dict]:
    dist = running.get("intensity_distribution") or {}
    low = dist.get("low_pct")
    if dist.get("available") and low is not None and low < 75:
        return [_ins("amber", "training", "Too much middle-intensity",
                     "Slow the easy runs down — the grey zone costs recovery without the "
                     "adaptation of true quality.",
                     f"{low:.0f}% easy vs the 80% polarised target.")]
    return []


def _evo2_rules(running: dict) -> list[dict]:
    ev = running.get("effective_vo2max") or {}
    if ev.get("available") and (ev.get("trend_per_week") or 0) < -0.05:
        return [_ins("amber", "training", "Effective VO₂max slipping",
                     "Usually recovery, heat or slowing easy pace — check sleep and readiness "
                     "before changing training.",
                     f"Down {abs(ev['trend_per_week']):.2f}/week over {ev.get('window_weeks')}w.")]
    return []


def _verdict(insights: list[dict], load: dict, todays_type: str | None) -> dict:
    rd = load.get("readiness_composite") or {}
    band = rd.get("band") or "unknown"
    reds = [i for i in insights if i["severity"] == "red"]
    quality = todays_type in {"tempo", "threshold", "intervals", "speed", "vo2max", "hills",
                              "fartlek", "race_pace", "long_run", "time_trial", "progressive"}
    if reds:
        action = reds[0]["advice"]
        headline = reds[0]["title"] + " — protect today."
        color = "red"
    elif band == "low":
        color = "red"
        headline = "Readiness is low — today is about absorbing, not adding."
        action = ("Swap today's session with your next easy day." if quality
                  else "Keep today genuinely easy — conversational or off.")
    elif band == "moderate":
        color = "amber"
        headline = "Trainable, but keep quality honest."
        action = ("Run today's session but hit the low end of every pace band."
                  if quality else "Easy day as planned — bank recovery.")
    else:
        color = "green"
        headline = "Green day — your body can absorb hard work."
        action = ("Full send on today's session — hit the targets." if quality
                  else "Easy day on a green reading — perfect for consistency.")
    return {"band": color, "readiness_band": band, "score": rd.get("score"),
            "driver": rd.get("dominant_driver"), "headline": headline, "action": action}


def daily_insights(profile: dict, load: dict, running: dict,
                   todays_type: str | None = None,
                   last_sync: str | None = None) -> dict:
    """Rule-based daily guidance. All inputs are plain dicts (profile dumped via Pydantic)."""
    insights: list[dict] = []
    insights += _illness_rules(load)
    insights += _hrv_rules(load)
    insights += _body_battery_rules(profile)
    insights += _tsb_rules(load)
    insights += _acwr_rules(load)
    insights += _monotony_rules(load)
    insights += _sleep_rules(load, profile)
    insights += _stress_rhr_rules(load)
    insights += _distribution_rules(running)
    insights += _evo2_rules(running)
    insights.sort(key=lambda i: SEV_ORDER.get(i["severity"], 9))

    age_hours = None
    if last_sync:
        try:
            dt = datetime.fromisoformat(last_sync)
            age_hours = round((datetime.now(dt.tzinfo) - dt) / timedelta(hours=1), 1)
        except ValueError:
            pass
    return {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_age_hours": age_hours, "stale": bool(age_hours and age_hours > 36),
            "verdict": _verdict(insights, load, todays_type),
            "items": insights}
