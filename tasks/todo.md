# Portal upgrade — Victor's 7 points (2026-07-22)

(Previous VM-runner task shipped 2026-07-21 — see git history of this file.)

- [ ] 1+2. Merge Overview into Today (single default tab): daily vitals strip (sleep, HRV, body battery, stress, resting HR, VO2max), session card, readiness, trending, recent activity, this-week, race predictions, RPE check-in. Remove `home` tab.
- [ ] 3. Fitness depth: freshness stamps (when each metric was last updated), actionable insight rules (online research → engine module → fitness.json `insights` → "Do this" UI section).
- [ ] 4. Plan owns the Garmin calendar: daily reconcile (push upcoming, delete orphans/stale), auto-trigger after plan changes, no manual pushing. (backend agent)
- [ ] 5. Calendar: month grid + day details stacked full-width (no side-by-side scroll dance); auto-select today.
- [ ] 6. HYROX tab: headline stats first, progression sections collapsible, less visual noise.
- [ ] 7. Telegram: styled HTML messages (emoji, bold headers, structure) for morning brief + coach headline. (backend agent)

Verify: ruff + pytest + Playwright on the live portal URL, then push.

## Review

(fill at end)
