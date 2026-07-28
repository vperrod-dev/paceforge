
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
