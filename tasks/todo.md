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
