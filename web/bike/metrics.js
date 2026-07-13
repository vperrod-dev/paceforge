// Training metrics for indoor cycling: NP/IF/TSS, W'bal, Coggan zones.
// Pure logic, no DOM — shared between browser UI and node selftests.

export const COGGAN_ZONES = [
  { z: 1, name: 'Recovery', lo: 0, hi: 0.55, color: '#7a8699' },
  { z: 2, name: 'Endurance', lo: 0.56, hi: 0.75, color: '#3da5d9' },
  { z: 3, name: 'Tempo', lo: 0.76, hi: 0.90, color: '#4caf7d' },
  { z: 4, name: 'Threshold', lo: 0.91, hi: 1.05, color: '#e6c229' },
  { z: 5, name: 'VO2max', lo: 1.06, hi: 1.20, color: '#f2792f' },
  { z: 6, name: 'Anaerobic', lo: 1.21, hi: 1.50, color: '#e0475b' },
  { z: 7, name: 'Sprint', lo: 1.51, hi: 99, color: '#b04ae0' },
];

export function zoneOf(pctFtp) {
  for (const zone of COGGAN_ZONES) {
    if (pctFtp <= zone.hi) return zone;
  }
  return COGGAN_ZONES[COGGAN_ZONES.length - 1];
}

export function powerZones(ftp) {
  return COGGAN_ZONES.map((zone) => ({
    z: zone.z,
    name: zone.name,
    color: zone.color,
    loW: Math.round(zone.lo * ftp),
    hiW: Math.round(zone.hi * ftp),
  }));
}

// 3-sample rolling mean for display smoothing.
export function smooth3s() {
  const buf = [];
  return (power) => {
    buf.push(power);
    if (buf.length > 3) buf.shift();
    return buf.reduce((a, b) => a + b, 0) / buf.length;
  };
}

const NP_WINDOW = 30;
// Sensor dropouts shouldn't credit minutes of energy to one sample.
const MAX_GAP_SEC = 3;

export class RideMetrics {
  #firstTs = null;
  #lastTs = null;
  #powerSum = 0;
  #powerCount = 0;
  #maxPower = 0;
  #kj = 0;
  #hrSum = 0;
  #hrCount = 0;
  #cadenceSum = 0;
  #cadenceCount = 0;
  // NP state: rolling 30-sample window + running sum of (rolling mean)^4.
  #window = [];
  #windowSum = 0;
  #p4Sum = 0;
  #p4Count = 0;

  add(tsMs, { power, hr, cadence } = {}) {
    if (typeof power !== 'number' || !Number.isFinite(power)) return;
    if (this.#firstTs === null) this.#firstTs = tsMs;
    const dt = this.#lastTs === null
      ? 0
      : Math.min(Math.max((tsMs - this.#lastTs) / 1000, 0), MAX_GAP_SEC);
    this.#lastTs = tsMs;

    this.#powerSum += power;
    this.#powerCount += 1;
    if (power > this.#maxPower) this.#maxPower = power;
    this.#kj += power * dt / 1000;

    this.#window.push(power);
    this.#windowSum += power;
    if (this.#window.length > NP_WINDOW) this.#windowSum -= this.#window.shift();
    if (this.#window.length === NP_WINDOW) {
      const mean = this.#windowSum / NP_WINDOW;
      this.#p4Sum += mean ** 4;
      this.#p4Count += 1;
    }

    if (typeof hr === 'number' && Number.isFinite(hr)) {
      this.#hrSum += hr;
      this.#hrCount += 1;
    }
    if (typeof cadence === 'number' && Number.isFinite(cadence)) {
      this.#cadenceSum += cadence;
      this.#cadenceCount += 1;
    }
  }

  get durationSec() {
    return this.#firstTs === null ? 0 : (this.#lastTs - this.#firstTs) / 1000;
  }

  get avgPower() {
    return this.#powerCount ? this.#powerSum / this.#powerCount : 0;
  }

  get maxPower() {
    return this.#maxPower;
  }

  get kj() {
    return this.#kj;
  }

  get np() {
    // Standard algorithm needs a full 30s window; fall back to average before that.
    if (!this.#p4Count) return this.avgPower;
    return (this.#p4Sum / this.#p4Count) ** 0.25;
  }

  intensityFactor(ftp) {
    return ftp > 0 ? this.np / ftp : 0;
  }

  tss(ftp) {
    const ifr = this.intensityFactor(ftp);
    return (this.durationSec / 3600) * ifr * ifr * 100;
  }

  get avgHr() {
    return this.#hrCount ? this.#hrSum / this.#hrCount : null;
  }

  get avgCadence() {
    return this.#cadenceCount ? this.#cadenceSum / this.#cadenceCount : null;
  }
}

// Differential W'bal (Skiba/Froncioni): burn above CP, exponential-ish refill below.
export class WBal {
  #cp;
  #wPrimeJ;
  #bal;
  #lastTs = null;

  constructor({ cp, wPrimeJ = 20000 }) {
    this.#cp = cp;
    this.#wPrimeJ = wPrimeJ;
    this.#bal = wPrimeJ;
  }

  add(tsMs, power) {
    const dt = this.#lastTs === null
      ? 0
      : Math.min(Math.max((tsMs - this.#lastTs) / 1000, 0), MAX_GAP_SEC);
    this.#lastTs = tsMs;
    if (power > this.#cp) {
      this.#bal -= (power - this.#cp) * dt;
    } else {
      this.#bal += (this.#cp - power) * ((this.#wPrimeJ - this.#bal) / this.#wPrimeJ) * dt;
    }
    this.#bal = Math.min(Math.max(this.#bal, 0), this.#wPrimeJ);
  }

  get value() {
    return this.#bal;
  }

  get pct() {
    return this.#wPrimeJ > 0 ? this.#bal / this.#wPrimeJ : 0;
  }
}
