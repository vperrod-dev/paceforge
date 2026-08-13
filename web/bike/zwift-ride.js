// Zwift Ride controller — reverse-engineered protocol.
// Sources: makinolo.com/blog/2024/07/26/zwift-ride-protocol/ and
// github.com/ajchellew/zwiftplay. Button enum + protobuf schema verified
// against the makinolo article (RideKeyPadStatus / RideAnalogKeyGroup).
import { Emitter, attemptReconnect } from './trainer.js';

// Firmware ≥ Feb 2025 advertises 0xFC82; older firmware uses the 128-bit UUID.
const SERVICE_NEW = 0xfc82;
const SERVICE_OLD = '00000001-19ca-4651-86e5-fa29dcdd09d1';
const CHAR_NOTIFY = '00000002-19ca-4651-86e5-fa29dcdd09d1';
const CHAR_WRITE = '00000003-19ca-4651-86e5-fa29dcdd09d1';
const CHAR_INDICATE = '00000004-19ca-4651-86e5-fa29dcdd09d1';

const MSG_CONTROLLER_NOTIFICATION = 0x23; // 0x19/0x15 are idle chatter
const IDLE_BITMAP = 0xffffffff; // all ones = nothing pressed (inverse logic)

// Bit → name, from makinolo's Ride enum (LEFT=0x1, UP=0x2, RIGHT=0x4,
// DOWN=0x8, A=0x10, B=0x20, Y=0x40, Z=0x100, then left/right shift,
// powerup, on/off). Bits 7 and 15 unused.
export const BUTTONS = {
  0: 'left', 1: 'up', 2: 'right', 3: 'down',
  4: 'a', 5: 'b', 6: 'y', 8: 'z',
  9: 'shiftUpLeft', 10: 'shiftDownLeft', 11: 'powerupLeft', 12: 'onoffLeft',
  13: 'shiftUpRight', 14: 'shiftDownRight', 16: 'powerupRight', 17: 'onoffRight',
};

// Minimal protobuf reader for RideKeyPadStatus:
//   field 1 varint  = 32-bit button bitmap (0 bit = pressed)
//   field 2 message = RideAnalogKeyGroup { repeated field 1 message
//     RideAnalogKeyPress { field 1 varint location, field 2 sint32 value } }
export function decodeControllerNotification(bytes) {
  if (bytes[0] !== MSG_CONTROLLER_NOTIFICATION) return null;
  let i = 1;
  // A truncated or spoofed notification must be rejected, not decoded into
  // garbage: reading past the end yields undefined, which silently becomes a
  // 0 byte and ends up emitted as a button press or analog value.
  const bad = () => { throw new RangeError('truncated notification'); };
  const byteAt = () => (i < bytes.length ? bytes[i++] : bad());
  const jump = n => { i += n; if (i > bytes.length) bad(); };
  const varint = () => {
    let v = 0, s = 0, b;
    do { b = byteAt(); v += (b & 0x7f) * 2 ** s; s += 7; } while (b & 0x80);
    return v;
  };
  const zigzag = n => (n % 2 ? -(n + 1) / 2 : n / 2);
  const skip = wire => {
    if (wire === 0) varint();
    else if (wire === 1) jump(8);
    else if (wire === 2) jump(varint());
    else if (wire === 5) jump(4);
    else bad();
  };
  const limit = n => (n <= bytes.length ? n : bad());
  const out = { bitmap: IDLE_BITMAP, analog: [] };
  try {
    while (i < bytes.length) {
      const tag = varint(), field = tag >> 3, wire = tag & 7;
      if (field === 1 && wire === 0) out.bitmap = varint();
      else if (field === 2 && wire === 2) {
        const groupEnd = limit(i + varint());
        while (i < groupEnd) {
          const gtag = varint();
          if ((gtag >> 3) === 1 && (gtag & 7) === 2) {
            const end = limit(i + varint());
            const press = { location: 0, value: 0 };
            while (i < end) {
              const ktag = varint(), kv = varint();
              if ((ktag >> 3) === 1) press.location = kv;
              else if ((ktag >> 3) === 2) press.value = zigzag(kv);
            }
            out.analog.push(press);
          } else skip(gtag & 7);
        }
      } else skip(wire);
    }
  } catch (err) {
    if (!(err instanceof RangeError)) throw err;
    return null;
  }
  return out;
}

// Edges only: buttons whose pressed state changed between two bitmaps.
export function diffButtons(prevBitmap, curBitmap) {
  const edges = [];
  for (const [bitStr, name] of Object.entries(BUTTONS)) {
    const bit = Number(bitStr), mask = 2 ** bit;
    const was = (prevBitmap & mask) === 0;
    const is = (curBitmap & mask) === 0;
    if (was !== is) edges.push({ bit, name, pressed: is });
  }
  return edges;
}

export class ZwiftRideControls extends Emitter {
  #device = null;
  #write = null;
  #intentional = false;
  #prevBitmap = IDLE_BITMAP;
  #analogPrev = new Map();
  #onRideOn = null;

  get connected() { return this.#device?.gatt?.connected ?? false; }
  get name() { return this.#device?.name ?? ''; }

  async connect() {
    this.#device = await navigator.bluetooth.requestDevice({
      // Only the LEFT controller pairs; it relays the right pod.
      filters: [{ services: [SERVICE_NEW] }, { services: [SERVICE_OLD] }],
      optionalServices: [SERVICE_NEW, SERVICE_OLD, 0x180f],
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
    let svc = null;
    for (const id of [SERVICE_NEW, SERVICE_OLD]) {
      try { svc = await server.getPrimaryService(id); break; } catch { /* try next */ }
    }
    if (!svc) throw new Error('Zwift Ride service not found');
    this.emit('status', `using service ${svc.uuid}`);

    let notify = null, write = null, indicate = null;
    try {
      notify = await svc.getCharacteristic(CHAR_NOTIFY);
      write = await svc.getCharacteristic(CHAR_WRITE);
      indicate = await svc.getCharacteristic(CHAR_INDICATE);
    } catch {
      // Unknown firmware layout: pick by properties instead.
      for (const c of await svc.getCharacteristics()) {
        const p = c.properties;
        this.emit('status', `characteristic ${c.uuid} notify=${p.notify} write=${p.write || p.writeWithoutResponse} indicate=${p.indicate}`);
        if (p.notify && !notify) notify = c;
        else if (p.indicate && !indicate) indicate = c;
        else if ((p.write || p.writeWithoutResponse) && !write) write = c;
      }
    }
    if (!notify || !write || !indicate) throw new Error('Zwift Ride characteristics not found');
    this.#write = write;

    notify.addEventListener('characteristicvaluechanged', e => {
      const v = e.target.value;
      this.#onMessage(new Uint8Array(v.buffer, v.byteOffset, v.byteLength));
    });
    await notify.startNotifications();

    const handshake = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('RideOn handshake timeout')), 3000);
      this.#onRideOn = () => { clearTimeout(timer); resolve(); };
    });
    indicate.addEventListener('characteristicvaluechanged', e => {
      const v = e.target.value;
      const bytes = new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
      // response begins with ASCII "RideOn"
      if (String.fromCharCode(...bytes.slice(0, 6)) === 'RideOn') this.#onRideOn?.();
    });
    await indicate.startNotifications();

    await write.writeValue(new TextEncoder().encode('RideOn'));
    await handshake;
    // No keepalive needed per makinolo/zwiftplay captures.
    this.#prevBitmap = IDLE_BITMAP;
    this.#analogPrev.clear();
    this.emit('status', `handshake ok with ${this.name}`);
  }

  #onMessage(bytes) {
    const msg = decodeControllerNotification(bytes);
    if (!msg) return;
    for (const edge of diffButtons(this.#prevBitmap, msg.bitmap)) this.emit('button', edge);
    this.#prevBitmap = msg.bitmap;
    for (const { location, value } of msg.analog) {
      if (this.#analogPrev.get(location) === value) continue;
      this.#analogPrev.set(location, value);
      this.emit('analog', { location, value });
    }
  }

  #onDrop = async () => {
    this.emit('disconnected');
    if (this.#intentional) return;
    await attemptReconnect(this.#device, () => this.#setup(), (ev, p) => this.emit(ev, p));
  };
}
