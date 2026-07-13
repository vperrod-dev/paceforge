// Heart Rate service 0x180D over Web Bluetooth.
import { Emitter, attemptReconnect } from './trainer.js';

const HR_SERVICE = 0x180d;
const HR_MEASUREMENT = 0x2a37;

// Flags byte bit0: 0 → uint8 bpm at offset 1, 1 → uint16le at offset 1.
export function parseHeartRate(view) {
  const bpm = view.getUint8(0) & 0x01 ? view.getUint16(1, true) : view.getUint8(1);
  return { bpm, ts: Date.now() };
}

export class HeartRateMonitor extends Emitter {
  #device = null;
  #intentional = false;

  get connected() { return this.#device?.gatt?.connected ?? false; }
  get name() { return this.#device?.name ?? ''; }

  async connect() {
    this.#device = await navigator.bluetooth.requestDevice({
      filters: [{ services: [HR_SERVICE] }],
      optionalServices: [0x180f],
    });
    this.#device.addEventListener('gattserverdisconnected', this.#onDrop);
    this.#intentional = false;
    await this.#setup();
    this.emit('connected');
  }

  async disconnect() {
    this.#intentional = true;
    if (this.connected) this.#device.gatt.disconnect();
  }

  async #setup() {
    const server = await this.#device.gatt.connect();
    const svc = await server.getPrimaryService(HR_SERVICE);
    const meas = await svc.getCharacteristic(HR_MEASUREMENT);
    meas.addEventListener('characteristicvaluechanged', e =>
      this.emit('data', parseHeartRate(e.target.value)));
    await meas.startNotifications();
    this.emit('status', `connected to ${this.name}`);
  }

  #onDrop = async () => {
    this.emit('disconnected');
    if (this.#intentional) return;
    await attemptReconnect(this.#device, () => this.#setup(), (ev, p) => this.emit(ev, p));
  };
}
