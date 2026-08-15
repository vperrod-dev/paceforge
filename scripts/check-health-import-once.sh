#!/usr/bin/env bash
# One-shot check: did the iOS Shortcuts automation's /health/import push land?
# Scheduled via a transient systemd timer for 2026-08-12 08:10 UTC (9:10am Dublin),
# 10 min after Victor's automation fires. Self-deletes after running (see caller).
set -euo pipefail

cd "$(dirname "$0")/.."
source ~/.config/paceforge/env

RESULT=$(python3 - <<'PY'
import json
from datetime import datetime, timezone

p = json.load(open("data/profile.json"))
hd = p.get("health_data") or {}
bc = hd.get("body_composition") or {}
weight_pts = bc.get("weight_kg") or []
last_sync = hd.get("last_sync")

fresh = False
if last_sync:
    ts = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
    fresh = (datetime.now(timezone.utc) - ts).total_seconds() < 3 * 3600

if fresh and weight_pts:
    latest = weight_pts[-1]
    print(f"OK|{latest['date']}|{latest['value']}|{last_sync}")
else:
    print(f"MISSING|{last_sync or 'never'}")
PY
)

STATUS="${RESULT%%|*}"

if [ "$STATUS" = "OK" ]; then
    IFS='|' read -r _ DATE VALUE SYNCED_AT <<< "$RESULT"
    MSG="PaceForge health-import check: it worked. Weight ${VALUE}kg logged for ${DATE} (synced ${SYNCED_AT})."
else
    LAST_SYNC="${RESULT#*|}"
    MSG="PaceForge health-import check: the 9am Shortcuts automation doesn't seem to have landed (last_sync=${LAST_SYNC}). No request access-log exists to see why — worth checking the Shortcut ran and didn't error."
fi

TG_SENDER=paceforge-health-import "$HOME/.claude/scripts/tgsend.sh" "${MSG}" > /dev/null
