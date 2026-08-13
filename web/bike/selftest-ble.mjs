// node web/bike/selftest-ble.mjs — pure-logic checks, no Bluetooth needed.
import assert from 'node:assert/strict';

import { parseIndoorBikeData, buildSetTargetPower, buildSetSimGrade } from './trainer.js';
import { decodeControllerNotification, diffButtons } from './zwift-ride.js';
import { MockTrainer } from './mock-trainer.js';

const hex = u8 => [...u8].map(b => b.toString(16).padStart(2, '0')).join(' ');

// 1. FTMS Indoor Bike Data: speed (bit0=0) + cadence (bit2) + power (bit6)
{
  const v = new DataView(new ArrayBuffer(8));
  v.setUint16(0, 0x0044, true);
  v.setUint16(2, 2500, true); // 25.00 km/h
  v.setUint16(4, 180, true);  // 90 rpm at 0.5 resolution
  v.setInt16(6, 250, true);   // 250 W
  const d = parseIndoorBikeData(v);
  assert.equal(d.speedKmh, 25);
  assert.equal(d.cadence, 90);
  assert.equal(d.power, 250);
  console.log('ok 1 - indoor bike data parser');
}

// 2. Control point payload builders
{
  assert.equal(hex(buildSetTargetPower(200)), '05 c8 00');
  assert.equal(hex(buildSetSimGrade(1.5)), '11 00 00 96 00 28 33');
  console.log('ok 2 - control point builders');
}

// 3. Zwift Ride protobuf: bitmap with bit0 (left) pressed + analog steer -50
{
  const idle = 0xffffffff;
  const payload = Uint8Array.of(
    0x23,
    0x08, 0xfe, 0xff, 0xff, 0xff, 0x0f,       // field1 varint 0xFFFFFFFE
    0x12, 0x06, 0x0a, 0x04, 0x08, 0x00, 0x10, 0x63, // analog group: loc 0, zigzag(99) = -50
  );
  const msg = decodeControllerNotification(payload);
  assert.equal(msg.bitmap, 0xfffffffe);
  assert.deepEqual(diffButtons(idle, msg.bitmap), [{ bit: 0, name: 'left', pressed: true }]);
  assert.deepEqual(msg.analog, [{ location: 0, value: -50 }]);
  // release edge back to idle
  assert.deepEqual(diffButtons(msg.bitmap, idle), [{ bit: 0, name: 'left', pressed: false }]);
  console.log('ok 3 - zwift ride decoder + button edges');
}

// 3b. Malformed notifications are rejected, not decoded into garbage. A
// glitched or spoofed BLE peripheral is the realistic trigger; before the
// bounds checks these read past the end and emitted phantom presses.
{
  const full = Uint8Array.of(
    0x23,
    0x08, 0xfe, 0xff, 0xff, 0xff, 0x0f,
    0x12, 0x06, 0x0a, 0x04, 0x08, 0x00, 0x10, 0x63,
  );
  // Every truncation that lands mid-field is rejected. Cuts 1 and 7 are the
  // only field boundaries in this frame (header alone, header + bitmap), and
  // those are complete messages that happen to carry fewer fields.
  const boundaries = new Set([1, 7]);
  for (let cut = 1; cut < full.length; cut++) {
    const msg = decodeControllerNotification(full.slice(0, cut));
    if (boundaries.has(cut)) assert.deepEqual(msg.analog, [], `cut ${cut} is a whole frame`);
    else assert.equal(msg, null, `truncation at ${cut} should be rejected`);
  }
  // varint that never terminates (continuation bit set on the last byte)
  assert.equal(decodeControllerNotification(Uint8Array.of(0x23, 0x08, 0xff)), null);
  // length prefix pointing past the end of the buffer
  assert.equal(decodeControllerNotification(Uint8Array.of(0x23, 0x12, 0x40, 0x0a)), null);
  // unknown wire type
  assert.equal(decodeControllerNotification(Uint8Array.of(0x23, 0x0c, 0x00)), null);
  // a valid frame still decodes after all of that
  assert.equal(decodeControllerNotification(full).bitmap, 0xfffffffe);
  console.log('ok 3b - zwift ride decoder rejects malformed notifications');
}

// 4. MockTrainer converges on ERG target
{
  const t = new MockTrainer({ tickMs: 5 });
  await t.connect();
  await t.setTargetPower(200);
  const samples = [];
  await new Promise(resolve => t.on('data', d => {
    samples.push(d);
    if (samples.length >= 6) resolve();
  }));
  await t.disconnect();
  const last = samples.at(-1).power;
  assert.ok(Math.abs(last - 200) <= 25, `power ${last} not within 200±25`);
  assert.ok(samples.every(s => s.cadence >= 85 && s.cadence <= 95), 'cadence out of 85-95');
  assert.equal(t.connected, false);
  console.log(`ok 4 - mock trainer erg convergence (last power ${last} W)`);
}

console.log('selftest-ble: all checks passed');
