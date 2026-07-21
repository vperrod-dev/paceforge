# VM runner — PaceForge off GitHub (phases 1+2), 2026-07-21

Victor: "I want it fixed and outside of github", "run the app on Caddy to keep everything on the VM".
Replaces backlog P1 (serve `_site`) + P2 (job runner replacing workflow_dispatch) in one move.

- [x] scripts/runner.py — stdlib HTTP runner on 127.0.0.1:8123; speaks the GitHub-API
      subset the portal already uses (dispatches / runs / jobs / issues / contents),
      global job lock (serialised data/ writes), commit+push per workflow parity,
      publish (build_site_data + rsync → /srv/paceforge) after every data change,
      Telegram brief + failure alerts, Claude steps via local `claude -p`
- [x] tests/test_runner_transforms.py — 8 tests, green
- [x] web/index.html + web/bike/view.js — GH_API base swap (LOCAL → 'api/gh'),
      githubToken.has() true when LOCAL; GitHub Pages path kept intact as rollback
- [x] ops/*.service|timer — installed + enabled; timers armed (sync Wed 05:45Z)
- [x] ~/.config/paceforge/env (0600): PACEFORGE_GARMIN_EMAIL, TG_TOKEN, TG_CHAT_ID
- [x] Caddy: blocks inserted (backup Caddyfile.bak-2026-07-21-paceforge), validated, reloaded
- [x] Verify: pytest 8/8; save-benchmarks facade dispatch 204 → run success (steps
      recorded); REAL sync run exercised the whole pipeline — commit `17a3b8e`
      pushed to GitHub, site republished, failure alert sent — but Garmin rejected
      the on-disk token; Playwright on the public URL: 401 unauth, 200 with auth,
      LOCAL=true, GH_API='api/gh', Today/Plan/Activity/Settings/Bike all render
- [x] Docs: CLAUDE.md VM-runner section; restore-checklist §0c; backlog updated

## Review

Phases 1+2 shipped in one move: portal + data + every button live on the VM with
zero GitHub dependency; workflows untouched (rollback path). One blocker left,
and it is Victor-only: the Garmin token on disk is invalid — `paceforge login`
is interactive (password + MFA). Until then sync/push/calendar-Garmin jobs fail
honestly (portal chip shows "Sync failing", Telegram alert fires); everything
else (plan, saves, coach, analyses, HYROX) is fully operational.
