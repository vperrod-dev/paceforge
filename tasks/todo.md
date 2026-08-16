# Calendar-first training (2026-08-15)

Victor: "running plans are a small piece that injects training into the calendar,
my calendar is the base of my overall training". Landing card + coach both behave
as if the running plan IS the training.

- [x] Today view: replace the single plan-first "Today's session" lead card with
      "Today's training" — every session scheduled today (calendar items + plan
      workouts, any sport, done or pending). Next-up only when today is empty.
- [x] Coach brief render: label the day, not the run.
- [x] Coach skill: reframe identity + daily-brief contract around the whole
      calendar; running plan = one injector.
- [x] Day pulse prompt + watch glance: whole-schedule context, not "running coach".
- [x] Planner: place quality/long runs off the athlete's booked class days
      (calendar-aware day roles) instead of scheduling blind; adapt's reflow
      won't drop a missed hard session onto a booked day either.
- [x] Tests + deploy + push.

## Review

Shipped in `db697ce`. 801 tests pass, ruff clean on touched files, runner
restarted, instance code updated.

Verified in the live portal (headless Chromium against the runner):
- today = one completed class → "Today's training · 1 session · 1 done", the
  class named, tomorrow's long run no longer promoted into today;
- three sessions today → all three listed, pending first, done dimmed;
- nothing today → "Next up · nothing today · next on <date>".

Open: the daily brief's `training` key only takes effect on the next `daily`
job (contract change); the weekly review picks up the whole-week framing on
Monday's `coach` run.
