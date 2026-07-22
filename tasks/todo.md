# PaceForge user layer — tasks/todo.md (2026-07-22)

Plan: ~/.claude/plans/ticklish-tickling-sprout.md
Approach: one runner instance per person (own checkout, port, env, Garmin token, data).

- [ ] 1. runner.py: commit_push skips push when no `origin` remote
- [ ] 2. Garmin email survives restart (_garmin_finish saves it, garmin_connect falls back)
- [ ] 3. web/index.html: neutral seed identity (not Victor)
- [ ] 4. ops/: systemd template units (runner/sync/autosync/coach @)
- [ ] 5. scripts/new-user.sh — provision an instance end to end
- [ ] 6. scripts/users.sh list|update|remove
- [ ] 7. Docs: CLAUDE.md multi-user section + README
- [ ] 8. Verify: ruff + pytest, throwaway instance `testuser` on 8129, isolation checks, remove it
- [ ] 9. Commit + push; os/links.yaml note

## Review
