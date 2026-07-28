# Perf audit — 2026-07-28

Same task already run 3+ times tonight (checkpoints 2:16am, 3:36am, 4:12am,
4:34am — see mem-search obs 8008-8013). This pass re-verifies each prior claim
against current source instead of re-guessing. Two verdicts flipped from
"leak/N+1" to "no issue" after reading the actual code — see below.

## Already fixed (this session, in git status as uncommitted)

- **RUNS unbounded growth** — `scripts/runner.py:89` now `del RUNS[:-200]`
  after append. Caps run history at 200 records. Done.
- **Power-trace O(n²) rebuild on long rides** — `web/bike/view.js:16`
  `MAX_TRACE_POINTS = 2000` + decimation logic added. Done.

## Corrected: NOT actual bugs (prior audit overstated)

- **"N+1 in actions.py" (obs 8008)** — checked all 28 `store.load_*()` call
  sites. Each CLI action loads what it needs once into a local var and reuses
  it (e.g. `actions.py:440-446` loads plan/activities/profile once each, not
  repeatedly). This is a one-process-per-CLI-invocation tool, not a
  request-scoped web handler — there's no shared request context to cache
  across, and no site re-fetches the same loader twice within one function.
  Not an N+1 pattern. No fix needed.
- **"38 setInterval/addEventListener, memory leak" (obs 8010/8011)** — no
  `setInterval` at all in `web/bike/view.js`. Every `addEventListener` in
  `attachPlayerUI` (keydown, visibilitychange, ride button, player events) has
  a matching `removeEventListener`/`.off()` in `detachPlayerUI` (view.js:639-648).
  Cleanup is correct. Not a leak.

## Still open (real, not yet fixed)

### 1. `allActivities()` re-fetches + re-parses on every tab switch
`web/index.html:609` — called from `/activities` (line 538) and `/feed`
(line 624, via `feedFromActivities`). Each call does two `loadJSON` fetches
(`activities.json` + `bike/rides.json`) and a merge+sort, even if the user
just switched tabs and nothing changed server-side.

```js
// web/index.html — add a short-TTL cache, invalidate on any mutating job result
let _actsCache = null, _actsCacheAt = 0;
async function allActivities() {
  if (_actsCache && Date.now() - _actsCacheAt < 15_000) return _actsCache;
  const [acts, rides] = await Promise.all([loadJSON('activities.json'), loadJSON('bike/rides.json')]);
  _actsCache = mergeAndSort(acts, rides);
  _actsCacheAt = Date.now();
  return _actsCache;
}
// call `_actsCache = null` after save-ride / sync jobs complete so new data shows immediately
```

### 2. Bike view: 50 `querySelector`/`getElementById` calls, several in hot paths
`web/bike/view.js` — `renderHome`, `renderPlayer`, `renderPost` each re-query
the DOM by id on every render call rather than caching the element refs.
Not a leak (elements are re-created each render since it's full innerHTML
re-render), but it's redundant lookups when only a value needs updating
(e.g. `updatePlayer(snap)` ticking every second — check it doesn't re-query
static containers on every tick).

```js
// if updatePlayer() re-queries the same node every tick, cache it once per attach:
function attachPlayerUI(p) {
  const els = {
    pause: document.getElementById('bk-pause'),
    watts: document.getElementById('bk-watts'),
    // ...
  };
  S.playerEls = els; // reuse in updatePlayer() instead of getElementById per tick
}
```
Lower priority than #1 — only worth it if `updatePlayer` ticks are measurably
slow; full-render paths (`renderHome`/`renderPost`) query once per navigation,
which is fine.

## Not re-checked this pass (already covered exhaustively, no new info)
- Checkpoint serialization O(n²) on runner (fixed per obs 7943-7945, 8012)
- SVG trace O(n²) (fixed per obs 7936-7937, 8013)
- React re-renders — n/a, this codebase has no React (vanilla JS + Web
  Components in `web/`)

## Bottom line
Two real fixes already landed and sit uncommitted in git status. One real
open item (#1, activities cache) worth ~10 lines. Everything else prior
audits flagged was either already fixed or was a false positive corrected
above.
