# Portal upgrade — Victor's 7 points (2026-07-22)

(Previous VM-runner task shipped 2026-07-21 — see git history of this file.)

- [x] 1+2. Merge Overview into Today (single default tab): daily vitals strip (sleep, HRV, body battery, resting HR, VO2max), session card, readiness, trending, recent activity, this-week, race predictions, RPE check-in. `home` tab removed.
- [x] 3. Fitness depth: engine/insights.py rule engine (TSB/ACWR/monotony/HRV/sleep-debt/body-battery/illness/80-20, cited thresholds) → fitness.json insights → "Today's call" panel + freshness chip; research report tasks/fitness-depth-research-2026-07-22.md.
- [x] 4. Plan owns the Garmin calendar: garmin_reconcile (push 3 weeks, delete stale + orphans), daily 06:20 UTC timer, auto-trigger after plan/recalibrate/calendar-edit jobs. First run: 9 pushed, 8 orphans removed.
- [x] 5. Calendar: month + day details stacked full-width; today auto-selected.
- [x] 6. HYROX tab: headline strip + focus card first, deep analysis in collapsible folds; 3 dead card fns removed.
- [x] 7. Telegram: HTML brief (emoji vitals, pace band, verdict) via `paceforge brief --telegram`; sample sent + delivered.

Verified: ruff clean, 409 tests pass, Playwright all-tabs no JS errors, public URL 200, pushed.

## Review

All 7 landed in one pass (frontend inline, backend via worktree agent, research via
web agent). Insights engine is deliberately transparent rules-with-citations, no ML.
Reconcile's first run removed 8 orphaned Garmin entries — the old-plan leftovers that
caused this morning's 5-vs-8 km confusion class of problem. Watch: Whoop-style
bedtime coach + weekly digest were researched but deferred (P2/P3 in the research doc).
