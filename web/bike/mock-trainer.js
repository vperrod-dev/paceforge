// Simulated trainer + HRM, duck-typed to FtmsTrainer / HeartRateMonitor.
import { Emitter } from './trainer.js';

// Each tick models 1 simulated second; power tracks target with tau ≈ 2 s.
const LAG_ALPHA = 1 - Math.exp(-1 / 2);

const noise = amp => (Math.random() + Math.random() + Math.random() - 1.5) * amp;

export class MockTrainer extends Emitter {
  #timer = null;
  #connected = false;
  #tickMs;
  #cadence = 90;
  #power = 150;
  #base = 150;
  #ergTarget = 150;
  #grade = 0;
  #resistance = 0;
  mode = null;

  constructor({ tickMs = 1000 } = {}) {
    super();
    this.#tickMs = tickMs;
  }

  get connected() { return this.#connected; }
  get name() { return 'Mock KICKR'; }
  set baseEffort(watts) { this.#base = watts; }

  async connect() {
    await new Promise(r => setTimeout(r, 300));
    this.#connected = true;
    this.#timer = setInterval(() => this.#tick(), this.#tickMs);
    this.emit('status', 'mock trainer ready');
    this.emit('connected');
  }

  async disconnect() {
    clearInterval(this.#timer);
    this.#connected = false;
    this.emit('disconnected');
  }

  async setTargetPower(watts) { this.mode = 'erg'; this.#ergTarget = watts; }
  async setSimGrade(gradePct) { this.mode = 'sim'; this.#grade = gradePct; }
  async setResistance(level) { this.mode = 'resistance'; this.#resistance = level; }
  async stopControl() { this.mode = null; }

  #target() {
    if (this.mode === 'erg') return this.#ergTarget;
    if (this.mode === 'sim') return Math.max(0, this.#base + this.#grade * 22);
    if (this.mode === 'resistance') return Math.max(0, this.#base + this.#resistance * 5);
    return this.#base;
  }

  #tick() {
    this.#power += (this.#target() - this.#power) * LAG_ALPHA;
    this.#cadence = Math.min(95, Math.max(85, this.#cadence + noise(3)));
    const power = Math.max(0, Math.round(this.#power + noise(2.7)));
    this.emit('data', {
      power,
      cadence: Math.round(this.#cadence * 2) / 2,
      speedKmh: Math.min(45, Math.max(8, power / 8)),
      ts: Date.now(),
    });
  }
}

export class MockHeartRate extends Emitter {
  #timer = null;
  #connected = false;
  #tickMs;
  #bpm = 75;
  #power = 0;

  // Pass the trainer so bpm follows its power output.
  constructor(trainer = null, { tickMs = 1000 } = {}) {
    super();
    this.#tickMs = tickMs;
    trainer?.on('data', d => { this.#power = d.power ?? 0; });
  }

  get connected() { return this.#connected; }
  get name() { return 'Mock HRM'; }

  async connect() {
    await new Promise(r => setTimeout(r, 300));
    this.#connected = true;
    this.#timer = setInterval(() => this.#tick(), this.#tickMs);
    this.emit('status', 'mock HRM ready');
    this.emit('connected');
  }

  async disconnect() {
    clearInterval(this.#timer);
    this.#connected = false;
    this.emit('disconnected');
  }

  #tick() {
    const target = 100 + this.#power * 0.35;
    this.#bpm += (target - this.#bpm) * 0.2 + noise(1.4);
    this.emit('data', { bpm: Math.round(this.#bpm), ts: Date.now() });
  }
}
