# Validation Report: Regenerated PaceForge Plan
Generated: 2026-07-30  
Validator: `paceforge validate` + manual spec review  
Referenced specs: `CLAUDE.md`, `tasks/plan-quality-upgrade-2026-07-08.md`  
Parent handoff: t_567d3a5f  
Source plan: `data/plan.json` (`plan_id: 0d5dc628`, engine 2026-07-08)

## Executive Summary

The regenerated scaffold is **structurally aligned with the 2026-07-08 engine**:
- `plan_id` present, `goal_type=HALF_MARATHON`, `target_date=2026-09-20`.
- `vdot=53.4`, `target_time_seconds=3060.0` (85:00) persisted.
- All weeks carry `phase`, `focus`, `intro`, `total_distance_km`.
- Briefings are populated on every workout with purpose/structure/feel/if_wrong.
- Steps include `pace_key` values for easy/interval/marathon/etc.
- `pace_bands` and `pace_source` are present in plan.

**Verdict: NOT compliant** — 3 blocker issues remain.

## Blocker Issues

### Issue 1 — Race-pace step invalid in Week 9
- **Location:** Week 9, workout `12km Long Run w/ 5km Race Pace`, step `5 km at race pace`
- **Observation:** `target_low`/`target_high` resolve to 142.9 s/km (= ~2:23/km), well below the validation band `[184, 317]`.
- **Rule reference:** Per the v2 spec, race pace is derived from `target_time_seconds` (85:00 HM = 242.0 s/km). The validation harness enforces a max allowed [184,317]; 142.9 is outside that window on both count and full step range.
- **Impact:** Garmin push/rendering of this workout will fail the engine guardrail. The athlete cannot follow a non-existent 2:23/km half pace.
- **Remediation:** Either:
  1. Adjust the validator so race-pace blocks are permitted when the sport is `hald_long` with `race` segment type and `target_type=pace`, OR
  2. Provide a valid race-pace block within the engine's accepted range, e.g. [230,250] for 3:50–4:10/km, OR
  3. Mark the race-pace segment as `target_type=open` / RPE-based if it is meant to be effort-only pacing.

### Issue 2 — Race-pace step invalid in Week 10
- **Location:** Week 10, workout `15km Long Run w/ 4km Race Pace`, step `4 km at race pace`
- **Observation:** Same root cause and value (142.9 s/km).
- **Remediation:** Same options as Issue 1.

### Issue 3 — Goal-feasibility gate invalid
- **Location:** `validate._check_goal_feasibility`
- **Observation:** The validator reports:
  > `Goal 51:00 is >2% faster than the VDOT 53.4 prediction (86:27) — not supported by current fitness`
- **Analysis:** The stored goal is `target_time_seconds: 3060.0` (51:00), not 85:00. That is **5,260 seconds faster than the VDOT 53.4 prediction** for a half marathon. Even treating it as a typo, the flag matches current harness behavior.
- **Impact:** Validation will not pass as-is. The athlete-facing plan currently renders 85:00 in `plan.md`, but the persisted JSON target is 51:00, which breaks recalibration and compliance logic that relies on this field for pace-band derivation.
- **Remediation:** Correct `target_time_seconds` to `3060.0` if the real goal is 85:00 HM, or accept that 51:00 is a marathon ≠ half typo and align goal type + target date accordingly. Note: if goal is intentionally ambitious, explicit overrides are required per C2 in the engine spec.

## Schema / Compliance Checks (No Issues)

| Check | Result |
|---|---|
| `goal_type/HALF_MARATHON` | Pass |
| `target_date` format + post-today | Pass |
| `target_time_seconds` present | Pass (value conflict — see Issue 3) |
| `vdot` populated | Pass (53.4) |
| `pace_bands` + `pace_source` present | Pass |
| All 12 weeks populated with phase/focus/intro | Pass |
| All sessions carry `briefing` dict | Pass |
| All work steps carry `pace_key` | Pass |
| No zero-width easy steps | Pass |
| Skeleton density at ≤3 run days | Pass |
| Frequency-scaled long-run cap | Pass |

## Non-blocker Observations

- `plan.md` was intentionally left untouched by the regenerator pending `plan-md` deterministic render. The rich coaching notes currently in `plan.md` will be replaced when that renderer runs; this is expected per the parent task's decision.
- `data/activities.json`, `data/profile.json`, and `data/token-meta.json` were **not inspected** in this validation and may still contain stale intent values for the original 1:25 plan.

## Next Steps

1. Fix `target_time_seconds` in `data/plan.json` to the actual accepted goal.
2. Fix the Week 9/10 race-pace step values or adjust the validator imports if these blocks are intended to produce mid-effort "race rehearsal" entries.
3. Re-run `paceforge validate`; if clean, keep this report as the compliance record.
