// Self-test: encode a synthetic ride, decode it with an independent minimal
// FIT reader, verify CRCs and values; exercise RideRecorder; optionally
// cross-check with python fitdecode. Run: node web/bike/selftest-fit.mjs
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { encodeRideFit, crc16 } from './fit.js';
import { RideRecorder } from './recorder.js';

const FIT_EPOCH_OFFSET_S = 631065600;
let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };

// ---------- minimal independent FIT decoder ----------
function decodeFit(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerSize = bytes[0];
  const dataSize = dv.getUint32(4, true);
  const defs = {};
  const messages = [];
  let off = headerSize;
  const end = headerSize + dataSize;
  while (off < end) {
    const hdr = bytes[off++];
    assert.ok(!(hdr & 0x80), 'compressed timestamp headers unsupported');
    const local = hdr & 0x0f;
    if (hdr & 0x40) {
      off++; // reserved
      const arch = bytes[off++];
      assert.equal(arch, 0, 'little-endian expected');
      const global = dv.getUint16(off, true); off += 2;
      const nFields = bytes[off++];
      const fields = [];
      for (let i = 0; i < nFields; i++) {
        fields.push({ num: bytes[off], size: bytes[off + 1] });
        off += 3;
      }
      if (hdr & 0x20) { const nDev = bytes[off++]; off += nDev * 3; }
      defs[local] = { global, fields };
    } else {
      const def = defs[local];
      assert.ok(def, `data record for undefined local type ${local}`);
      const msg = { global: def.global, f: {} };
      for (const f of def.fields) {
        msg.f[f.num] = f.size === 1 ? bytes[off] : f.size === 2 ? dv.getUint16(off, true) : dv.getUint32(off, true);
        off += f.size;
      }
      messages.push(msg);
    }
  }
  assert.equal(off, end, 'decoder consumed exactly dataSize bytes');
  return messages;
}

// ---------- synthetic 10-min ride: 600 samples, 2 laps ----------
const startMs = Date.UTC(2026, 0, 1, 10, 0, 0);
const records = [];
for (let i = 0; i < 600; i++) {
  records.push({ tMs: startMs + i * 1000, power: i < 300 ? 150 : 250, hr: 140, cadence: 90, speedKmh: 30, distanceM: (i * 30) / 3.6 });
}
const laps = [
  { startMs, endMs: startMs + 300000 },
  { startMs: startMs + 300000, endMs: startMs + 599000 },
];
const fit = encodeRideFit({ startTimeMs: startMs, records, laps, ftp: 200 });
const fitPath = join(tmpdir(), 'pf-selftest-ride.fit');
writeFileSync(fitPath, fit);

// header
ok(fit[0] === 14, 'header size 14');
ok(fit[1] === 0x20, 'protocol version 2.0');
ok(String.fromCharCode(...fit.subarray(8, 12)) === '.FIT', '.FIT magic');
const dv = new DataView(fit.buffer);
ok(dv.getUint32(4, true) === fit.length - 16, 'header data size matches');
ok(dv.getUint16(12, true) === crc16(fit.subarray(0, 12)), 'header CRC verifies');
ok(dv.getUint16(fit.length - 2, true) === crc16(fit.subarray(0, fit.length - 2)), 'file CRC verifies');

// round-trip decode
const msgs = decodeFit(fit);
const byGlobal = (g) => msgs.filter((m) => m.global === g);
const recs = byGlobal(20);
ok(recs.length === 600, 'record count 600');
const expectedFirstTs = startMs / 1000 - FIT_EPOCH_OFFSET_S;
ok(recs[0].f[253] === expectedFirstTs, 'first timestamp FIT-epoch-offset correct');
ok(recs.every((r, i) => i === 0 || r.f[253] > recs[i - 1].f[253]), 'timestamps strictly monotonic');
ok(recs[0].f[7] === 150 && recs[599].f[7] === 250, 'record powers survive round-trip');
ok(recs[10].f[6] === Math.round((30 / 3.6) * 1000), 'speed encoded as m/s*1000');

const lapMsgs = byGlobal(19);
ok(lapMsgs.length === 2, 'lap count 2');
ok(lapMsgs[0].f[19] === 150 && lapMsgs[1].f[19] === 250, 'lap avg_power 150/250');
ok(lapMsgs[0].f[7] === 300000, 'lap 1 total_elapsed_time 300000 ms');

const session = byGlobal(18)[0];
ok(session, 'session message present');
ok(session.f[20] === 200, 'session avg_power 200');
ok(session.f[21] === 250, 'session max_power 250');
ok(session.f[5] === 2 && session.f[6] === 6, 'sport cycling / sub_sport indoor');
ok(session.f[26] === 2, 'session num_laps 2');
ok(byGlobal(0).length === 1 && byGlobal(34).length === 1, 'file_id + activity present');

// ---------- RideRecorder ----------
const fakeStorage = {
  data: {},
  setItem(k, v) { this.data[k] = String(v); },
  getItem(k) { return this.data[k] ?? null; },
  removeItem(k) { delete this.data[k]; },
};
let clock = startMs;
const rec = new RideRecorder({ storage: fakeStorage, now: () => clock });
rec.start(100);
for (let i = 1; i <= 3600; i++) {
  clock = startMs + i * 1000;
  rec.addSample({ power: 100, hr: 150, cadence: 85, speedKmh: 30 });
}
ok(fakeStorage.data['pf-bike-ride-inprogress'], 'checkpoint written during ride');
ok(fakeStorage.data['pf-bike-ride-inprogress:1'] !== undefined, 'checkpoints persist incremental chunks');
const recovered = RideRecorder.recover(fakeStorage);
ok(recovered && recovered.startTimeMs === startMs && recovered.ftp === 100, 'recover() returns saved ride');
ok(recovered.records.length >= 3540, 'recovered records cover ride up to last checkpoint');
ok(recovered.records[0].power === 100, 'recovered sample round-trips');

const result = rec.stop();
ok(fakeStorage.data['pf-bike-ride-inprogress'] === undefined, 'stop() clears checkpoint');
ok(Object.keys(fakeStorage.data).every((k) => !k.startsWith('pf-bike-ride-inprogress')),
  'stop() clears chunk keys too');
// pre-chunk single-blob checkpoint (old on-disk format) must still recover
fakeStorage.setItem('pf-bike-ride-inprogress',
  JSON.stringify({ startTimeMs: 1, ftp: 200, records: [{ tMs: 1, power: 5 }], laps: [] }));
const legacy = RideRecorder.recover(fakeStorage);
ok(legacy && legacy.records.length === 1 && legacy.ftp === 200, 'legacy single-blob checkpoint recovers');
fakeStorage.removeItem('pf-bike-ride-inprogress');
ok(result.laps.length === 1, 'no lap() calls -> single whole-ride lap');
ok(Math.abs(result.summary.durationSec - 3600) < 1, 'duration 3600s');
ok(Math.abs(result.summary.tss - 100) <= 1, `TSS 60min @ FTP = 100±1 (got ${result.summary.tss.toFixed(2)})`);
ok(Math.abs(result.summary.np - 100) < 0.01, 'NP = 100 for constant power');
ok(Math.abs(result.summary.kj - 360) < 1, 'kJ ~ 360 for 100W x 1h');
ok(result.summary.avgPower === 100 && result.summary.avgHr === 150, 'avg power/hr correct');
ok(Math.abs(result.summary.distanceM - 29991.7) < 10, 'distance ~30km from 30km/h x 1h');

// ---------- optional python fitdecode cross-check ----------
const py = `
import sys
try:
    import fitdecode
except ImportError:
    print('NOIMPORT'); sys.exit(0)
n = 0; avg = None
with fitdecode.FitReader(sys.argv[1]) as r:
    for frame in r:
        if isinstance(frame, fitdecode.FitDataMessage):
            if frame.name == 'record': n += 1
            if frame.name == 'session': avg = frame.get_value('avg_power')
print(f'OK {n} {avg}')
`;
const python = process.env.PF_FIT_PYTHON || 'python3'; // point at a venv python if system pip is PEP-668 locked
let pyRes = spawnSync(python, ['-c', py, fitPath], { encoding: 'utf8', timeout: 60000 });
if (pyRes.stdout && pyRes.stdout.startsWith('NOIMPORT')) {
  const pip = spawnSync(python, ['-m', 'pip', 'install', '--user', '--quiet', 'fitdecode'], { encoding: 'utf8', timeout: 120000 });
  if (pip.status === 0) pyRes = spawnSync(python, ['-c', py, fitPath], { encoding: 'utf8', timeout: 60000 });
}
if (pyRes.status === 0 && pyRes.stdout.startsWith('OK')) {
  const [, n, avg] = pyRes.stdout.trim().split(' ');
  ok(Number(n) === 600, 'fitdecode: 600 records');
  ok(Number(avg) === 200, 'fitdecode: session avg_power 200');
  console.log('fitdecode cross-check: PASSED (independent decoder accepted the file)');
} else {
  console.log('fitdecode cross-check: SKIPPED (python/fitdecode unavailable)');
}

console.log(`selftest: ${checks} checks passed (${fit.length} byte FIT file at ${fitPath})`);
process.exit(0);
