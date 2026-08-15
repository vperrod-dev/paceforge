#!/usr/bin/env bash
# Decommission the old Azure hosting — this is what stops the monthly bill.
# DESTRUCTIVE. Run ONLY after you've verified the file-based flow works
# (paceforge sync / push) and migrated your data (scripts/migrate_from_sqlite.py).
#
# Requires: az login. Set PACEFORGE_RG to the resource group. Pass --yes to skip prompt.
set -euo pipefail

RG="${PACEFORGE_RG:-}"
if [ -z "$RG" ]; then
  echo "Set PACEFORGE_RG to the resource group containing the PaceForge resources." >&2
  exit 1
fi

echo "Resource group: $RG"
echo "Will DELETE:"
echo "  - App Service: paceforge-dev"
echo "  - App Service: paceforge-app"
echo "  - Container Registry: paceforgeacr"

if [ "${1:-}" != "--yes" ]; then
  read -r -p "Type 'delete' to proceed: " confirm
  [ "$confirm" = "delete" ] || { echo "Aborted."; exit 1; }
fi

failed=0

# This script's whole job is confirming the bill stopped, so a delete that failed
# because the login expired or the role lacks permission must never read the same
# as a resource that is genuinely gone — only Azure's own not-found error counts
# as "already gone", everything else is a resource that may still be billing.
delete_resource() {
  local label="$1"; shift
  local out rc=0
  out=$("$@" 2>&1) || rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "$label: deleted"
  elif printf '%s' "$out" | grep -qiE 'ResourceNotFound|was not found|does not exist'; then
    echo "$label: already gone"
  else
    echo "$label: DELETE FAILED (az exit $rc) — assume it is STILL BILLING" >&2
    printf '%s\n' "$out" >&2
    failed=1
  fi
}

delete_resource paceforge-dev  az webapp delete --resource-group "$RG" --name paceforge-dev
delete_resource paceforge-app  az webapp delete --resource-group "$RG" --name paceforge-app
delete_resource paceforgeacr   az acr delete --resource-group "$RG" --name paceforgeacr --yes

if [ "$failed" -ne 0 ]; then
  echo "NOT done — at least one resource was not deleted. Fix the errors above and re-run." >&2
  exit 1
fi

echo "Done. Check the Azure portal Cost Management to confirm nothing is still billing."
