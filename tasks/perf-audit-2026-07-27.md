# PaceForge perf audit — 2026-07-27

Third pass today (see claude-mem 7516, 7538). Confirmed all three still live in tree, unfixed.

## 1. Unbounded SVG trace rebuild — `web/bike/view.js:706-707` (HIGH)

Every 1s tick during a ride, full `S.trace` array rejoins into SVG points string.
Free rides: `player.js:29` sets `totalSec = Infinity` → trace grows forever.
1h ride = 3600+ points, 3h = 10000+. Each tick's `join()` cost grows with elapsed
time → cumulative O(n²) work over ride duration. Frame drops right when athlete
is deep in effort.

```js
// web/bike/view.js:706-707 (current)
S.trace.push(`${x.toFixed(1)},${y.toFixed(1)}`);
u.trace.setAttribute('points', S.trace.join(' '));

// fix: cap to last N points (e.g. 1 hour @ 1Hz)
const MAX_TRACE_POINTS = 3600;
S.trace.push(`${x.toFixed(1)},${y.toFixed(1)}`);
if (S.trace.length > MAX_TRACE_POINTS) S.trace.shift();
u.trace.setAttribute('points', S.trace.join(' '));
```

## 2. O(n²) localStorage checkpoint — `web/bike/recorder.js:120-132` (MEDIUM)

`checkpoint()` fires every 60s, serializes the **entire** `records` array each
time. Total work over a d-second ride = O((d/60)²). 3h ride → ~180 checkpoints,
each stringifying a bigger array → periodic multi-hundred-ms main-thread stalls.

```js
// fix: checkpoint a resumable summary + tail, not full history
checkpoint(tMs) {
  this.lastSaveMs = tMs;
  const TAIL = 100;
  try {
    this.storage?.setItem(STORAGE_KEY, JSON.stringify({
      startTimeMs: this.startTimeMs,
      ftp: this.ftp,
      recordCount: this.records.length,
      recordsTail: this.records.slice(-TAIL),
      laps: this.laps,
    }));
  } catch { /* storage full/unavailable: keep recording in memory */ }
}
```
Note: full `records` array must still live in memory for the final `.FIT` export —
only the checkpoint write shrinks, not the in-memory array.

## 3. `RUNS` list memory leak — `scripts/runner.py:68,88` (MEDIUM)

Long-running systemd process (`paceforge-runner`) appends every job dispatch to
`RUNS: list[dict]` forever — sync 3x/day, coach, analyze, etc. Never trimmed.
Over weeks of uptime this accumulates hundreds of records with nested step-lists.

```python
# scripts/runner.py — in Run.__init__ / wherever RUNS.append(self.rec) happens (line 88)
with RUNS_LOCK:
    RUNS.append(self.rec)
    del RUNS[:-500]   # keep last 500 only; endpoints already only slice tails
```

## Not applicable
- **N+1 queries**: no DB — `data/*.json` flat files via `store.py`. `load_all_details()`
  (store.py:202) reads all detail files once per action call, already batched
  into a dict; not called in a loop. No N+1 pattern found.
- **React re-renders**: no React in this repo. `web/` is vanilla JS/HTML.
- **DoS/unbounded body read**: already fixed same day (`scripts/runner.py:814`, `MAX_BODY` cap).

## Root cause link
Issues 1 and 2 share one root: free-ride duration is unbounded (`totalSec = Infinity`),
but the trace array and checkpoint payload were never given a size budget to match.
Fixing the cap in both places closes the leak; no need to bound ride duration itself.
