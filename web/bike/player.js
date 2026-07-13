// Ride engine: drives one ride at a 1s tick — targets from the step timeline,
// ERG control, recording, live metrics. No DOM; the view subscribes to events.
//   'tick'   → snapshot object (every active second)
//   'prompt' → { message } when a textevent fires
//   'step'   → { index, step } on interval boundaries
//   'done'   → workout timeline exhausted
import { Emitter } from './trainer.js';
import { RideRecorder } from './recorder.js';
import { RideMetrics, WBal, smooth3s, zoneOf } from './metrics.js';

const KEEPALIVE_S = 5;
const BEST60_WINDOW = 60;

export class RidePlayer extends Emitter {
  // mode: 'workout' | 'ramp' | 'freeride'. Free ride has no steps: ERG holds a
  // manual watt target, ERG-off leaves control to the view (sim grade / gears).
  constructor({ steps = [], ftp, wprimeJ = 20000, trainer, hrm = null, mode = 'workout', storage } = {}) {
    super();
    this.steps = steps;
    this.ftp = ftp;
    this.trainer = trainer;
    this.hrm = hrm;
    this.mode = mode;
    this.t = 0;
    this.bias = 100;
    this.erg = true;
    this.paused = false;
    this.ergWatts = Math.round(0.6 * ftp); // free-ride manual ERG target
    this.totalSec = steps.length ? steps[steps.length - 1].start + steps[steps.length - 1].duration : Infinity;
    this.recorder = new RideRecorder(storage ? { storage } : {});
    this.metrics = new RideMetrics();
    this.wbal = new WBal({ cp: ftp, wPrimeJ: wprimeJ });
    this.smooth = smooth3s();
    this.live = { power: 0, power3s: 0, hr: null, cadence: null, speedKmh: null };
    this.best60 = 0;
    this.startTimeMs = null;
  }

  #timer = null;
  #lastStep = -1;
  #lastSent = null;
  #lastSentAt = -Infinity;
  #best60Buf = [];
  #best60Sum = 0;
  #firedPrompts = new Set();
  #onData = null;
  #onHr = null;

  start() {
    this.startTimeMs = Date.now();
    this.recorder.start(this.ftp);
    this.#onData = d => this.#handleData(d);
    this.trainer.on('data', this.#onData);
    if (this.hrm) {
      this.#onHr = d => { this.live.hr = d.bpm; };
      this.hrm.on('data', this.#onHr);
    }
    this.#timer = setInterval(() => this.#tick(), 1000);
    this.#tick(); // immediate first target
  }

  #handleData(d) {
    if (d.power != null) {
      this.live.power = d.power;
      this.live.power3s = this.smooth(d.power);
    }
    if (d.cadence != null) this.live.cadence = d.cadence;
    if (d.speedKmh != null) this.live.speedKmh = d.speedKmh;
    if (this.paused) return;
    this.recorder.addSample({ power: d.power, hr: this.live.hr, cadence: d.cadence, speedKmh: d.speedKmh });
    this.metrics.add(d.ts, { power: d.power, hr: this.live.hr, cadence: d.cadence });
    if (d.power != null) this.wbal.add(d.ts, d.power);
    if (this.mode === 'ramp' && d.power != null) {
      this.#best60Buf.push(d.power);
      this.#best60Sum += d.power;
      if (this.#best60Buf.length > BEST60_WINDOW) this.#best60Sum -= this.#best60Buf.shift();
      if (this.#best60Buf.length === BEST60_WINDOW) {
        this.best60 = Math.max(this.best60, this.#best60Sum / BEST60_WINDOW);
      }
    }
  }

  stepIndexAt(t) {
    for (let i = 0; i < this.steps.length; i += 1) {
      if (t < this.steps[i].start + this.steps[i].duration) return i;
    }
    return this.steps.length - 1;
  }

  // Target watts at second t: linear interpolation across ramps, ×bias.
  targetAt(t) {
    if (this.mode === 'freeride') return this.erg ? this.ergWatts : null;
    const step = this.steps[this.stepIndexAt(t)];
    if (!step || step.powerStartW == null) return null;
    const frac = step.duration > 0 ? (t - step.start) / step.duration : 0;
    const w = step.powerStartW + (step.powerEndW - step.powerStartW) * frac;
    return Math.round(w * this.bias / 100);
  }

  #tick() {
    if (this.paused) return;
    const idx = this.steps.length ? this.stepIndexAt(this.t) : -1;
    if (idx !== this.#lastStep) {
      if (this.#lastStep >= 0) this.recorder.lap();
      this.#lastStep = idx;
      if (idx >= 0) this.emit('step', { index: idx, step: this.steps[idx] });
    }
    const step = idx >= 0 ? this.steps[idx] : null;
    for (const ev of step?.textEvents ?? []) {
      if (ev.atSec <= this.t && ev.atSec > this.t - 3 && !this.#firedPrompts.has(ev)) {
        this.#firedPrompts.add(ev);
        this.emit('prompt', { message: ev.message });
      }
    }
    this.#control();
    this.emit('tick', this.snapshot());
    this.t += 1;
    if (this.t >= this.totalSec) {
      clearInterval(this.#timer);
      this.#timer = null;
      this.emit('done');
    }
  }

  #control() {
    if (!this.erg) return;
    const target = this.targetAt(this.t);
    if (target == null) return;
    if (target !== this.#lastSent || this.t - this.#lastSentAt >= KEEPALIVE_S) {
      this.#lastSent = target;
      this.#lastSentAt = this.t;
      this.trainer.setTargetPower(target).catch(() => {}); // dropped writes recover on the next tick
    }
  }

  snapshot() {
    const idx = this.steps.length ? this.stepIndexAt(this.t) : -1;
    const step = idx >= 0 ? this.steps[idx] : null;
    const target = this.targetAt(this.t);
    return {
      t: this.t,
      totalSec: this.totalSec,
      remaining: Number.isFinite(this.totalSec) ? Math.max(0, this.totalSec - this.t) : null,
      stepIndex: idx,
      step,
      stepElapsed: step ? this.t - step.start : 0,
      stepRemaining: step ? step.start + step.duration - this.t : null,
      nextStep: idx >= 0 && idx + 1 < this.steps.length ? this.steps[idx + 1] : null,
      target,
      power: this.live.power,
      power3s: this.live.power3s,
      zone: this.ftp > 0 ? zoneOf(this.live.power3s / this.ftp) : null,
      hr: this.live.hr,
      cadence: this.live.cadence,
      np: this.metrics.np,
      if: this.metrics.intensityFactor(this.ftp),
      tss: this.metrics.tss(this.ftp),
      kj: this.metrics.kj,
      wbalJ: this.wbal.value,
      wbalPct: this.wbal.pct,
      bias: this.bias,
      erg: this.erg,
      ergWatts: this.ergWatts,
      paused: this.paused,
      best60: this.best60,
    };
  }

  pause() {
    if (this.paused) return;
    this.paused = true;
    this.recorder.pause();
    this.emit('tick', this.snapshot());
  }

  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.recorder.resume();
    this.#lastSentAt = -Infinity; // re-assert target immediately
  }

  togglePause() { this.paused ? this.resume() : this.pause(); }

  skip() {
    const idx = this.stepIndexAt(this.t);
    if (idx < 0 || idx + 1 >= this.steps.length) return;
    this.t = this.steps[idx + 1].start;
    this.#lastSentAt = -Infinity;
  }

  back() {
    const idx = this.stepIndexAt(this.t);
    if (idx < 0) return;
    const step = this.steps[idx];
    // >3s into a step → restart it; otherwise jump to the previous one.
    this.t = (this.t - step.start > 3 || idx === 0) ? step.start : this.steps[idx - 1].start;
    this.#lastSentAt = -Infinity;
  }

  addBias(delta) {
    this.bias = Math.min(150, Math.max(50, this.bias + delta));
    this.#lastSentAt = -Infinity;
  }

  addWatts(delta) {
    this.ergWatts = Math.min(1500, Math.max(0, this.ergWatts + delta));
    this.#lastSentAt = -Infinity;
  }

  async setErg(on) {
    this.erg = on;
    if (on) {
      this.#lastSentAt = -Infinity;
    } else {
      this.#lastSent = null;
      await this.trainer.stopControl().catch(() => {});
    }
  }

  // Ends the ride and returns { records, laps, summary } (null if nothing recorded).
  stop() {
    if (this.#timer) clearInterval(this.#timer);
    this.#timer = null;
    this.trainer.off('data', this.#onData);
    if (this.hrm && this.#onHr) this.hrm.off('data', this.#onHr);
    this.trainer.stopControl().catch(() => {});
    return this.recorder.stop();
  }
}
