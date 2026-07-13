// FTMS (Fitness Machine Service) trainer control over Web Bluetooth.
// Spec refs: FTMS v1.0 — service 0x1826, Indoor Bike Data 0x2AD2,
// Control Point 0x2AD9, Machine Status 0x2ADA, Feature 0x2ACC,
// Supported Power Range 0x2AD8.

export const FTMS_SERVICE = 0x1826;
const INDOOR_BIKE_DATA = 0x2ad2;
const CONTROL_POINT = 0x2ad9;
const MACHINE_STATUS = 0x2ada;
const MACHINE_FEATURE = 0x2acc;
const SUPPORTED_POWER_RANGE = 0x2ad8;

const OP_REQUEST_CONTROL = 0x00;
const OP_RESET = 0x01;
const OP_SET_RESISTANCE = 0x04;
const OP_SET_TARGET_POWER = 0x05;
const OP_START_RESUME = 0x07;
const OP_SET_SIM_PARAMS = 0x11;
const CP_RESPONSE = 0x80;
const CP_SUCCESS = 0x01;

export class Emitter {
  #listeners = new Map();
  on(event, cb) {
    if (!this.#listeners.has(event)) this.#listeners.set(event, new Set());
    this.#listeners.get(event).add(cb);
    return this;
  }
  off(event, cb) {
    this.#listeners.get(event)?.delete(cb);
  }
  emit(event, payload) {
    this.#listeners.get(event)?.forEach(cb => cb(payload));
  }
}

export const RECONNECT_DELAYS = [1000, 3000, 8000];

// Shared unexpected-drop recovery: retry with backoff, run device-specific
// re-setup, emit 'connected' again on success.
export async function attemptReconnect(device, setup, emit) {
  for (const ms of RECONNECT_DELAYS) {
    emit('status', `connection lost, reconnecting in ${ms / 1000}s…`);
    await new Promise(r => setTimeout(r, ms));
    try {
      await device.gatt.connect();
      await setup();
      emit('connected');
      return true;
    } catch (e) {
      emit('status', `reconnect failed: ${e.message}`);
    }
  }
  emit('status', 'reconnect gave up');
  return false;
}

// Indoor Bike Data 0x2AD2. Little-endian; flags uint16 decide which fields
// follow, in bit order. bit0 (More Data) INVERTED: 0 means speed present.
export function parseIndoorBikeData(view) {
  const flags = view.getUint16(0, true);
  let o = 2;
  const out = { ts: Date.now() };
  if (!(flags & 0x0001)) { out.speedKmh = view.getUint16(o, true) * 0.01; o += 2; }
  if (flags & 0x0002) o += 2; // average speed
  if (flags & 0x0004) { out.cadence = view.getUint16(o, true) * 0.5; o += 2; }
  if (flags & 0x0008) o += 2; // average cadence
  if (flags & 0x0010) { // total distance, uint24 metres
    out.distanceM = view.getUint16(o, true) | (view.getUint8(o + 2) << 16);
    o += 3;
  }
  if (flags & 0x0020) o += 2; // resistance level
  if (flags & 0x0040) { out.power = view.getInt16(o, true); o += 2; }
  // remaining fields (avg power, energy, HR, MET, times) not emitted
  return out;
}

export function buildSetTargetPower(watts) {
  const v = new DataView(new ArrayBuffer(3));
  v.setUint8(0, OP_SET_TARGET_POWER);
  v.setInt16(1, Math.round(watts), true);
  return new Uint8Array(v.buffer);
}

// Indoor Bike Simulation Parameters: wind m/s (0.001), grade % (0.01),
// crr (0.0001), wind resistance coefficient kg/m (0.01).
export function buildSetSimGrade(gradePct, { windMps = 0, crr = 0.004, cwa = 0.51 } = {}) {
  const v = new DataView(new ArrayBuffer(7));
  v.setUint8(0, OP_SET_SIM_PARAMS);
  v.setInt16(1, Math.round(windMps * 1000), true);
  v.setInt16(3, Math.round(gradePct * 100), true);
  v.setUint8(5, Math.round(crr * 10000));
  v.setUint8(6, Math.round(cwa * 100));
  return new Uint8Array(v.buffer);
}

export function buildSetResistance(level) {
  // ponytail: FTMS table is ambiguous on Set Target Resistance Level width
  // (uint8 vs sint16); implemented as uint8 at 0.1 resolution — verify on hardware.
  const raw = Math.max(0, Math.min(255, Math.round(level * 10)));
  return Uint8Array.of(OP_SET_RESISTANCE, raw);
}

export class FtmsTrainer extends Emitter {
  #device = null;
  #cp = null;
  #queue = Promise.resolve();
  #pending = null;
  #intentional = false;
  #controlAcquired = false;
  mode = null; // 'erg' | 'sim' | 'resistance' | null
  powerRange = null;
  features = null;

  get connected() { return this.#device?.gatt?.connected ?? false; }
  get name() { return this.#device?.name ?? ''; }
  get controlAcquired() { return this.#controlAcquired; }

  async connect() {
    this.#device = await navigator.bluetooth.requestDevice({
      filters: [{ services: [FTMS_SERVICE] }],
      optionalServices: [0x1818, 0x180f], // Cycling Power, Battery
    });
    this.#device.addEventListener('gattserverdisconnected', this.#onDrop);
    this.#intentional = false;
    await this.#setup();
    this.emit('connected');
  }

  async disconnect() {
    this.#intentional = true;
    if (this.connected) this.#device.gatt.disconnect(); // 'disconnected' fires via #onDrop
  }

  async setTargetPower(watts) {
    await this.#cpRequest(buildSetTargetPower(watts));
    this.mode = 'erg';
  }

  async setSimGrade(gradePct, opts) {
    await this.#cpRequest(buildSetSimGrade(gradePct, opts));
    this.mode = 'sim';
  }

  async setResistance(level) {
    await this.#cpRequest(buildSetResistance(level));
    this.mode = 'resistance';
  }

  async stopControl() {
    await this.#cpRequest(Uint8Array.of(OP_RESET));
    this.mode = null;
    this.#controlAcquired = false;
  }

  async #setup() {
    const server = await this.#device.gatt.connect();
    const svc = await server.getPrimaryService(FTMS_SERVICE);

    const bike = await svc.getCharacteristic(INDOOR_BIKE_DATA);
    bike.addEventListener('characteristicvaluechanged', e =>
      this.emit('data', parseIndoorBikeData(e.target.value)));
    await bike.startNotifications();

    this.#cp = await svc.getCharacteristic(CONTROL_POINT);
    this.#cp.addEventListener('characteristicvaluechanged', this.#onCpIndication);
    await this.#cp.startNotifications();

    try {
      const status = await svc.getCharacteristic(MACHINE_STATUS);
      status.addEventListener('characteristicvaluechanged', e =>
        this.emit('status', `machine status 0x${e.target.value.getUint8(0).toString(16)}`));
      await status.startNotifications();
    } catch { /* optional on some trainers */ }

    try {
      const f = await (await svc.getCharacteristic(MACHINE_FEATURE)).readValue();
      this.features = f.getUint32(0, true);
    } catch { /* optional */ }

    try {
      const r = await (await svc.getCharacteristic(SUPPORTED_POWER_RANGE)).readValue();
      this.powerRange = { min: r.getInt16(0, true), max: r.getInt16(2, true), step: r.getUint16(4, true) };
    } catch { /* optional */ }

    await this.#cpRequest(Uint8Array.of(OP_REQUEST_CONTROL));
    this.#controlAcquired = true;
    try {
      await this.#cpRequest(Uint8Array.of(OP_START_RESUME));
    } catch (e) {
      this.emit('status', `start/resume rejected: ${e.message}`); // non-fatal on some trainers
    }
    this.emit('status', `connected to ${this.name}`);
  }

  // Serialize control-point writes: only one outstanding request; resolve on
  // the 0x80 indication response.
  #cpRequest(bytes) {
    const run = this.#queue.then(() => new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#pending = null;
        reject(new Error('control point response timeout'));
      }, 5000);
      this.#pending = {
        op: bytes[0],
        resolve: () => { clearTimeout(timer); resolve(); },
        reject: e => { clearTimeout(timer); reject(e); },
      };
      this.#cp.writeValueWithResponse(bytes).catch(e => {
        clearTimeout(timer);
        this.#pending = null;
        reject(e);
      });
    }));
    this.#queue = run.catch(() => {});
    return run;
  }

  #onCpIndication = e => {
    const v = e.target.value;
    if (v.getUint8(0) !== CP_RESPONSE || !this.#pending) return;
    if (v.getUint8(1) !== this.#pending.op) return;
    const p = this.#pending;
    this.#pending = null;
    const result = v.getUint8(2);
    if (result === CP_SUCCESS) p.resolve();
    else p.reject(new Error(`control op 0x${p.op.toString(16)} failed: result 0x${result.toString(16)}`));
  };

  #onDrop = async () => {
    this.#controlAcquired = false;
    this.#pending?.reject(new Error('disconnected'));
    this.#pending = null;
    this.emit('disconnected');
    if (this.#intentional) return;
    await attemptReconnect(this.#device, () => this.#setup(), (ev, p) => this.emit(ev, p));
  };
}
