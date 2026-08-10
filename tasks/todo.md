# PaceForge gap-closing — tasks/todo.md (2026-08-10)

Plan: ~/.claude/plans/we-have-been-doing-recursive-wadler.md
Research: tasks/running-plan-methodology-research-2026-08-10.md

- [x] Step 0: Garmin calendar cleared (21 entries), plan.json+plan.md deleted,
      52-class snapshot saved (tasks/step0-classes-snapshot-2026-08-10.json),
      4 recurring Un1t classes re-added interim via add-session (24 on Garmin)
- [x] WS1: auto-sync — coalescing, light mode, 15-min timers + 429 backoff,
      WARP env, honest button, focus/interval refresh, chip thresholds,
      Hermes day-pulse
- [x] WS2: intake-driven planning (form, VDOT from stated times, volume from
      intake) + variety engine (low-vol variants, Rotation, kill 25km gate,
      fartlek dosing, briefing variation, weekly-quality validator,
      variant_key + hold_back_progression)
- [x] WS3: calendar decoupling — ScheduledItem/calendar.json, add_session
      rewrite, calendar_view union endpoint, item-level Garmin push,
      re-add classes from snapshot, Add-activity editor
- [x] WS4: Today redesign + mobile-first audit (390px, touch targets,
      bottom sheets, lead-card date-sort fix, metricCard dupe)
- [x] WS5: Coach tab (HYROX folds under Fitness), analyses surfaced,
      weekly content_md rendered, markdown renderer, RPE poll closure
- [x] WS6: watch push fidelity (recovery no-target, stepOrder/childStepId,
      repeat descriptions, _fallback_steps by sport, description budget,
      TT open, validate parity, push status) + on-watch confirm (VICTOR)
      + CIQ data field (watch/)

## Review (2026-08-10, all six workstreams shipped same day)

**Shape.** Every gap traced to one root cause each: sync UX (no automation +
dishonest toast), plans (history-capped volume + modulo selection), calendar
(no entity — projections of plan.json), Today (no hierarchy + wrong lead
workout), coach (outputs with no surface), watch (fallback steps + payload
shape). Fixes are structural, not cosmetic.

**Found while building:**
- job_garmin_clear_calendar defaults to dry-run — a "completed" run had
  deleted nothing (verify state, not exit codes).
- commit_push hard-failed on a named path that stopped existing
  (data/plan.json between plans) — autosync died on git add.
- grid items default min-width:auto — ONE long word widened the whole page
  on mobile; .dash-grid>*{min-width:0} was the real fix, not overflow hacks.
- daemon-thread test worker outlived its monkeypatched STATE_DIR and wrote
  noop runs into live runs.jsonl (twice) — always join workers in-fixture.
- The pinned garminconnect fork models childStepId natively; only the repeat
  group description needed extra="allow".

**Deliberate ceilings (ponytail):**
- Calendar union is client-side (data/*.json already served) — server-side
  /calendar endpoint only if a non-browser consumer appears.
- Difficulty slider (quality-count preference) skipped — level covers it.
- Day-pulse slots are fixed hours, not metric-change-driven.
- CIQ field v1 has no server comms — the FIT file carries all targets.

**Awaiting Victor:** one real on-watch run to confirm step rendering
(pace-band gauge, repeat structure, silent recoveries), then optionally the
CIQ field sideload (watch/README.md). Plan rebuild via the new intake form
whenever ready — Sept 20 race has no plan scaffolding until then.

## 2026-08-10 PM — opportunities batch (all shipped)
- [x] Same-day rewrite (tired/sick/time buttons → engine rewrite → watch push)
- [x] Proactive coach (HRV/RHR/HRR Telegram alerts, daily dedupe)
- [x] Race prognosis (effective VO2max + shape, VDOT prior clamp) + Races card
- [x] Coach proposals queue (pending-changes.json, Accept/Dismiss, validate-gated)
- [x] MCP: get_activities / adjust_today / propose_plan_change
- [x] Watch: Race field; Coach field LOAD % + DRIFT alert
- [x] Consistency heatmap + streak (Form tab)
- [x] plan.ics phone-calendar feed
- Calibration open: watch LOAD % uses zone-weighted minutes vs server type-weight
  estimate — skew possible, tune after first workouts. Telegram INBOUND commands
  skipped (bot getUpdates single-consumer conflict) — portal buttons only.
