// Ride recorder: sample buffer + localStorage crash-safety checkpoints.
// No DOM; storage object injectable so it runs in node tests.

import { normalizedPower } from './fit.js';
import { NS } from './ns.js';

const STORAGE_KEY = 'pf-bike-ride-inprogress' + NS;
const CHECKPOINT_MS = 60000;
const MAX_GAP_S = 5; // ponytail: cap sample gaps (tab sleep) instead of modeling pauses per-gap

function defaultStorage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export class RideRecorder {
  constructor({ storage, now } = {}) {
    this.storage = storage === undefined ? defaultStorage() : storage;
    this.now = now || Date.now.bind(Date);
    this.running = false;
  }

  start(ftp) {
    this.discard(); // clear any stale checkpoint chunks from an earlier ride
    this.ftp = ftp || null;
    this.startTimeMs = this.now();
    this.records = [];
    this.savedRecords = 0; // records already persisted into chunk keys
    this.savedChunks = 0;
    this.laps = [];
    this.lapStartMs = this.startTimeMs;
    this.paused = false;
    this.pausedMs = 0;
    this.pauseStartMs = null;
    this.distanceM = 0;
    this.lastSampleMs = null;
    this.lastSaveMs = this.startTimeMs;
    this.running = true;
  }

  addSample({ power, hr, cadence, speedKmh } = {}) {
    if (!this.running || this.paused) return;
    const tMs = this.now();
    if (speedKmh != null && this.lastSampleMs != null) {
      const dtS = Math.min((tMs - this.lastSampleMs) / 1000, MAX_GAP_S);
      this.distanceM += (speedKmh / 3.6) * dtS;
    }
    this.lastSampleMs = tMs;
    const rec = { tMs };
    if (power != null) rec.power = power;
    if (hr != null) rec.hr = hr;
    if (cadence != null) rec.cadence = cadence;
    if (speedKmh != null) {
      rec.speedKmh = speedKmh;
      rec.distanceM = this.distanceM;
    }
    this.records.push(rec);
    if (tMs - this.lastSaveMs >= CHECKPOINT_MS) this.checkpoint(tMs);
  }

  lap() {
    if (!this.running) return;
    const tMs = this.now();
    this.laps.push({ startMs: this.lapStartMs, endMs: tMs });
    this.lapStartMs = tMs;
  }

  pause() {
    if (!this.running || this.paused) return;
    this.paused = true;
    this.pauseStartMs = this.now();
  }

  resume() {
    if (!this.running || !this.paused) return;
    this.paused = false;
    this.pausedMs += this.now() - this.pauseStartMs;
    this.pauseStartMs = null;
  }

  stop() {
    if (!this.running) return null;
    if (this.paused) this.resume();
    const endMs = this.lastSampleMs ?? this.now();
    if (endMs > this.lapStartMs) this.laps.push({ startMs: this.lapStartMs, endMs });
    this.running = false;
    this.discard();

    const durationSec = Math.max(0, (endMs - this.startTimeMs - this.pausedMs) / 1000);
    const powers = this.records.map((r) => r.power ?? 0);
    const hasPower = this.records.some((r) => r.power != null);
    const np = hasPower ? normalizedPower(powers) : null;
    const if_ = np != null && this.ftp ? np / this.ftp : null;
    const tss = if_ != null ? ((durationSec * np * if_) / (this.ftp * 3600)) * 100 : null;
    let kj = 0;
    this.records.forEach((r, i) => {
      if (r.power == null) return;
      const dtS = i ? Math.min((r.tMs - this.records[i - 1].tMs) / 1000, MAX_GAP_S) : 1;
      kj += (r.power * dtS) / 1000;
    });

    return {
      records: this.records,
      laps: this.laps,
      summary: {
        durationSec,
        avgPower: hasPower ? mean(this.records.map((r) => r.power)) : null,
        maxPower: hasPower ? Math.max(...this.records.map((r) => r.power ?? 0)) : null,
        np,
        if_,
        tss,
        kj: hasPower ? kj : null,
        avgHr: mean(this.records.map((r) => r.hr)),
        avgCadence: mean(this.records.map((r) => r.cadence)),
        distanceM: this.distanceM,
      },
    };
  }

  // Each checkpoint persists only the records since the last one into its own
  // `${STORAGE_KEY}:<i>` chunk key, plus a small meta blob — re-stringifying
  // the whole accumulated array every 60s was O(n²) over a multi-hour ride.
  // Records are append-only, so already-written chunks never go stale; the
  // meta (laps can grow) is tiny and rewritten each time.
  checkpoint(tMs) {
    this.lastSaveMs = tMs;
    try {
      if (this.records.length > this.savedRecords) {
        this.storage?.setItem(
          `${STORAGE_KEY}:${this.savedChunks}`,
          JSON.stringify(this.records.slice(this.savedRecords)),
        );
        this.savedChunks += 1;
        this.savedRecords = this.records.length;
      }
      this.storage?.setItem(STORAGE_KEY, JSON.stringify({
        startTimeMs: this.startTimeMs,
        ftp: this.ftp,
        laps: this.laps,
        chunks: this.savedChunks,
      }));
    } catch {
      // storage full/unavailable: keep recording, ride stays in memory
    }
  }

  discard() {
    try {
      const meta = JSON.parse(this.storage?.getItem(STORAGE_KEY) ?? 'null');
      for (let i = 0; i < (meta?.chunks || 0); i++) this.storage?.removeItem(`${STORAGE_KEY}:${i}`);
      this.storage?.removeItem(STORAGE_KEY);
    } catch {
      try { this.storage?.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    }
  }

  static recover(storage = defaultStorage()) {
    try {
      const raw = storage?.getItem(STORAGE_KEY);
      if (!raw) return null;
      const saved = JSON.parse(raw);
      if (saved?.chunks == null) return saved; // pre-chunk single-blob checkpoint
      const records = [];
      for (let i = 0; i < saved.chunks; i++) {
        const chunk = storage?.getItem(`${STORAGE_KEY}:${i}`);
        if (chunk) records.push(...JSON.parse(chunk));
      }
      return { startTimeMs: saved.startTimeMs, ftp: saved.ftp, records, laps: saved.laps };
    } catch {
      return null;
    }
  }
}

function mean(values) {
  const xs = values.filter((v) => v != null);
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}
