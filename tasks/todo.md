# PaceForge user layer — tasks/todo.md (2026-07-22)

Plan: ~/.claude/plans/ticklish-tickling-sprout.md
Approach: one runner instance per athlete (own checkout, port, env, Garmin token, data).

- [x] 1. runner.py: commit_push skips push when no `origin` remote
- [x] 2. Garmin email survives restart (_garmin_finish saves it, actions._garmin_email falls back)
- [x] 3. Per-instance identity in the UI (/auth/whoami + boot fetch, no hardcoded Victor)
- [x] 4. ops/: systemd template units (runner/sync/autosync/coach @, randomized delays)
- [x] 5. scripts/users.py add|list|update|remove (clone, env, units, Caddy route)
- [x] 6. Namespace browser storage per portal path (localStorage is per-origin, one host)
- [x] 7. Docs: CLAUDE.md "Multi-user" section + README "Sharing it with other athletes"
- [x] 8. Verified: ruff + 445 tests + 3 bike selftests; throwaway `testuser` instance
      provisioned, logged in, isolation checked, sync job failed cleanly with a
      local-only commit, both portals rendered in a browser, instance removed
- [x] 9. Committed + pushed

## Review

**Shape.** Multi-tenancy comes from the OS, not the app: `store.DATA_DIR` is an
import-time global and the runner hardcodes `REPO_DIR/data`, so threading a user
id through jobs would have been a large, risky refactor. One process per athlete
in its own checkout gets the same result with ~40 lines of app change, because
every path was already relative to the process's cwd or an env var.

**Found while building, not in the plan:**
- `localStorage`/`sessionStorage` are per-ORIGIN, and all instances share one
  hostname — plan drafts, pending RPE, benchmarks and bike state would have bled
  across portals. Every key is now suffixed with the portal's base path. Side
  effect: existing browsers re-seed their cached plan draft from `data/plan.json`.
- `git pull` cannot update an instance: this repo commits Victor's own training
  data to the same branch, so `update` copies the code directories instead and
  each instance's git history stays purely its own athlete's data.
- The displayed athlete name was circular (`profileMeta()` returned the seed
  constant it was supposed to replace), so every portal would have said "Victor".
  It now comes from `/auth/whoami` + `token-meta.json`.
- `build_site_data.py` crashed on a virgin instance, masking the real "connect
  Garmin first" message. It now exits cleanly when there is no profile yet.

**Open / optional:** the Settings page still shows a "GitHub Integration" panel
naming `vperrod/paceforge` (pre-existing: `githubToken.has()` returns true on the
VM); harmless but worth hiding when `LOCAL`, if friends ask what it is.

---

## GitHub removal (2026-07-22, Victor: "we wont be back to gitactions or make the repo public")

- [x] `.github/workflows/` deleted (19 files)
- [x] Frontend: PAT storage, token guards, Settings→GitHub card, auth headers, `ref`, the
      Pages branch of GH_API — all gone; two dead raw.githubusercontent.com fetches (HYROX
      import) now read `./data/hyrox.json`; user-facing text says "job", not "workflow"
- [x] Runner/CLI/skill/doc framing: the runner is the backend, not a stand-in
- [x] Docs: README (3 ways, not 4), CLAUDE.md (jobs + env contract), AGENTS.md, and the OS
      side (restore-checklist §0c CLOSED, registry constraints, backlog items closed/moot)
- [x] Memory: paceforge-vm-runner + paceforge-garmin-token no longer describe a live GitHub path
- [x] Nuno's instance updated + its stale .github/workflows removed

**Bug found while verifying, fixed at the root:** `commit_push` committed the whole index,
so a job that fired while this checkout had unrelated staged work swept it into a "data:"
commit and pushed it (that is how the workflow deletion landed inside commit `2d89c1d`).
It now commits only its own pathspec — `tests/test_runner_commit.py` covers it, and the
next real sync was verified to touch `data/` only.

**Left deliberately:** the `/gh/repos/<o>/<r>/…` URL shapes on both sides. They are the
runner's own contract now (owner/repo ignored, no token); rewriting the wire would touch
~20 call sites and two route tables to change nothing a user sees.

## Bike history + workout library (2026-07-28)

- [x] Fix stuck "pending" ride duplicates: reconcile localStorage pending list against
      rides.json on every home render (matched by date, the runner's idempotency key)
- [x] Ride-detail view: history rows clickable → power/HR chart with zone bands, FTP line,
      time-in-zone bar, stats + notes; rides saved from now on carry a downsampled `trace`
      ([sec, watts, hr] ≤400 pts, sanitized server-side in `append_ride`)
- [x] Workout library 10 → 18: Endurance 60/120, 3x12 Sweet Spot, 3x10 Threshold,
      30/30s 3x10, 6x1 Anaerobic, Tempo 60, Big Gear 5x5 (stats computed by the app's own
      parser; selftest-formats requires index sorted by filename and recomputes every entry)
- [x] Verified: ruff + pytest (35 passed), node selftests (126 passed), runner restarted,
      served view.js/index.json checked on 8223, nunoduarte instance updated (8224)

Note: yesterday's ride (2026-07-27) predates trace capture — its detail view shows stats
only. The duplicate "pending" copy of it disappears on first page load with the new code.
