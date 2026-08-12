
## 2026-07-21 — portal Garmin login saga
- Victor cannot/won't use a terminal: every operator flow must live in the portal (login page, Garmin connect, MFA). Build UI mechanisms, don't prescribe CLI commands.
- No basic-auth prompts, ever — they also silently break same-origin fetch() flows. Cookie-session login page instead.
- "Wait N hours and retry" is not a fix for Victor — find the mechanism (per-IP 429 → different egress via WARP proxy) and kill the root cause.
- Never restart a stateful service while a user flow may be in flight — the runner restart destroyed his in-memory MFA session mid-login. Deploy hot paths between flows, or announce first.
- Browser autofill puts the SITE password into any password field on the page (sent the portal password to Garmin → 401). autocomplete=new-password + delayed blanking + explicit warning.

## 2026-07-27 — "digest it" means the whole surface, not one metric
Victor: bike rides must be digested like Garmin work. First pass wired them
into training load only and listed the remaining surfaces as "say if wanted"
— he had already said it. When he asks for X to be treated like Y, port the
FULL treatment (load, lists, Today, detail views) in one turn; offering the
remainder as follow-up reads as not doing the job.

## 2026-07-28 — "evaluate all workouts" means ALL, not the plan-matched subset
Third time Victor asked for automatic coach evaluation of every workout
(running, cardio, bike). The gate was `pending_analyses` walking plan.json:
only completed workouts with `matched_activity_ids` qualified, so every
unplanned session (indoor cardio, off-plan runs, bike rides) fell through —
and the coach skill doctrine ("auto for planned workouts") reinforced it.
When a selection filter decides what automation touches, check the filter
against the user's stated universe ("all X") — not against what the pipeline
happens to index. Coverage complaints repeated 3× = the selector is wrong,
not the executor.

## 2026-08-02 — cardio scheduling saga: don't act on an unanswered question, verify claims live
- Victor rejected an AskUserQuestion ("wants to clarify") and gave no answer. I proceeded with the plan-rebuild option anyway on his earlier-stated preference — wrong. A rejected/unanswered question means STOP and wait, not "pick the most likely option and continue." He was furious ("I DIDNT ASK YOU TO REBUILD THE PLAN").
- "Delete the plan" was literal and standalone — not "delete and I'll tell you what's next." After he deleted it, I kept treating a running plan as a hard dependency for unrelated features (cardio class scheduling) instead of questioning why that dependency existed at all. When a user deletes X and Y breaks, the fix is usually "Y shouldn't need X," not "recreate X."
- Reported "fixed" after unit tests + one curl smoke test, twice, before it was actually fixed end-to-end in the real UI (a job-completion polling bug meant the calendar never refreshed after scheduling — confirmed only via real Playwright clicks, not API calls). Backend-correct ≠ user sees it. For any UI-surfaced fix, drive the actual browser flow before calling it done, not just the API/job it triggers.
- A claimed timestamp comparison (`created_at >= dispatchedAt`) silently failed because the server truncates to whole seconds — ms-precision client comparisons against second-precision server timestamps are a recurring trap; prefer monotonic ids over time comparisons for "did my thing complete" polling.

## 2026-08-10 — plan ambition must come from intake, not scraped history
Victor, on the repetitive-plans complaint: "I do not want you to focus on what is
my volume... my volume is low because your plans are shit." The engine anchored
peak/weekly volume to recent Garmin mileage (2.2× clamp, 1.15× weekly cap), which
plus the <25 km quality kill-switch produced easy/easy/long weeks — a spiral:
boring plan → athlete runs less → history drops → next plan flatter. The athlete's
GOAL (race, target time, stated recent times, declared volume) governs the plan;
Garmin history is for prefills, suggestions and live metrics (readiness, load,
adaptation) — advisory, never a cap. Generalization: when output quality drives
the very signal used as input constraint, the constraint is circular — anchor on
stated intent, validate with history, don't govern by it.

## 2026-08-12 — "unplanned" analyses: the matcher's 90% gate vs WU/CD estimates
Victor: "the coach analysis makes no sense... I did a plan activity!" Today's
`4km Tempo Run` never linked to the treadmill session because
`estimated_distance_meters` prices the 10-min warm-up/cool-down at easy pace
(7.0 km planned) while the actual run was 5.43 km — 78%, under `_MIN_SIMILARITY`
0.9 — so the coach analysed a planned session as unplanned. Generalization: when
a matcher compares an ESTIMATE against a MEASUREMENT, the gate has to tolerate
the estimate's own systematic bias; here the workout's own paced work steps are
the honest floor (`_did_the_work`).

Two process lessons from the same session:
- The nightly auto-repair `git rm --cached`'d the ignored-but-tracked `data/`
  state files (58c38b6). Every job that commits a NAMED path then dies on
  `git add … exited 1` (save-rpe, twice) — and nothing was versioned for 11 h.
  An "obvious" security repair that contradicts a documented invariant needs the
  invariant restated where the repair agent will read it (CLAUDE.md + AGENTS.md).
- `git revert` of that commit RESTORED THE OLD BLOBS INTO THE WORKING TREE,
  silently overwriting live untracked-since state (profile.json, rpe.json —
  one athlete-logged RPE lost). Before reverting a `git rm --cached` commit,
  copy the working tree files aside; `--no-commit` does not mean "index only".

## 2026-08-12 — "the plan" means the athlete's whole week, not the running plan
Victor: "the coach is not counting planned cycling or planned cardio as the plan
— only the running. The running plan is one thing and the coach analysis
another." Every layer had inherited plan.json as the definition of planned:
per-activity analyses called booked classes "calendar-only … not part of the
running plan", `weekly_compliance` listed their activities under `unplanned`,
and `brief` said "nothing scheduled" on a class day. Since the 2026-08-10
decoupling, `data/calendar.json` IS the week and the running plan merely
contributes workouts to it — code and prompts have to follow the data model.
Also: telling the coach agent to look the match up itself failed twice even with
explicit instructions. Resolve facts the deterministic layer already knows
(`planned_session()` in runner.py) and hand the agent the answer; judgement is
the model's job, lookups are not.
