// Minimal FIT activity-file encoder (clean-room, from the public FIT
// protocol description at developer.garmin.com/fit/protocol/).
// Produces: file_id, record*, lap*, session, activity — enough for
// intervals.icu and Strava to accept an indoor ride.

const FIT_EPOCH_OFFSET_S = 631065600; // 1989-12-31T00:00:00Z in Unix seconds

const CRC_TABLE = [
  0x0000, 0xcc01, 0xd801, 0x1400, 0xf001, 0x3c00, 0x2800, 0xe401,
  0xa001, 0x6c00, 0x7800, 0xb401, 0x5000, 0x9c01, 0x8801, 0x4400,
];

// FIT CRC-16 (table algorithm from the protocol spec)
export function crc16(bytes, crc = 0) {
  for (const b of bytes) {
    let tmp = CRC_TABLE[crc & 0xf];
    crc = (crc >> 4) & 0x0fff;
    crc = crc ^ tmp ^ CRC_TABLE[b & 0xf];
    tmp = CRC_TABLE[crc & 0xf];
    crc = (crc >> 4) & 0x0fff;
    crc = crc ^ tmp ^ CRC_TABLE[(b >> 4) & 0xf];
  }
  return crc;
}

// FIT base types
const ENUM = 0x00;
const UINT8 = 0x02;
const UINT16 = 0x84;
const UINT32 = 0x86;
const UINT32Z = 0x8c;
const SIZE = { [ENUM]: 1, [UINT8]: 1, [UINT16]: 2, [UINT32]: 4, [UINT32Z]: 4 };
const INVALID = {
  [ENUM]: 0xff, [UINT8]: 0xff, [UINT16]: 0xffff,
  [UINT32]: 0xffffffff, [UINT32Z]: 0,
};

// 30-sample (~30s @ 1Hz) rolling-average normalized power
export function normalizedPower(powers) {
  if (!powers.length) return 0;
  const win = Math.min(30, powers.length);
  let acc = 0;
  let sum4 = 0;
  let n = 0;
  for (let i = 0; i < powers.length; i++) {
    acc += powers[i];
    if (i >= win) acc -= powers[i - win];
    if (i >= win - 1) {
      sum4 += (acc / win) ** 4;
      n++;
    }
  }
  return n ? (sum4 / n) ** 0.25 : 0;
}

class Writer {
  constructor() {
    this.bytes = [];
  }
  u8(v) {
    this.bytes.push(v & 0xff);
  }
  u16(v) {
    this.u8(v);
    this.u8(v >>> 8);
  }
  u32(v) {
    this.u8(v);
    this.u8(v >>> 8);
    this.u8(v >>> 16);
    this.u8(v >>> 24);
  }
  value(type, v) {
    if (v == null || Number.isNaN(v)) v = INVALID[type];
    else v = Math.max(0, Math.min(Math.round(v), INVALID[type] === 0 ? 0xffffffff : INVALID[type] - (type === UINT32Z ? 0 : 1)));
    if (SIZE[type] === 1) this.u8(v);
    else if (SIZE[type] === 2) this.u16(v);
    else this.u32(v);
  }
  definition(local, global, fields) {
    this.u8(0x40 | local);
    this.u8(0); // reserved
    this.u8(0); // architecture: little-endian
    this.u16(global);
    this.u8(fields.length);
    for (const f of fields) {
      this.u8(f.num);
      this.u8(SIZE[f.type]);
      this.u8(f.type);
    }
  }
  data(local, fields, values) {
    this.u8(local);
    fields.forEach((f, i) => this.value(f.type, values[i]));
  }
}

const toFitTs = (ms) => Math.round(ms / 1000) - FIT_EPOCH_OFFSET_S;

function avg(values) {
  const xs = values.filter((v) => v != null);
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

function max(values) {
  const xs = values.filter((v) => v != null);
  return xs.length ? Math.max(...xs) : null;
}

// kJ from power samples using timestamp deltas (gaps capped at 5s)
function kilojoules(records) {
  let j = 0;
  for (let i = 0; i < records.length; i++) {
    if (records[i].power == null) continue;
    const dtS = i ? Math.min((records[i].tMs - records[i - 1].tMs) / 1000, 5) : 1;
    j += records[i].power * dtS;
  }
  return j / 1000;
}

export function encodeRideFit({ startTimeMs, records, laps = [], ftp, totals = {} }) {
  if (!records || !records.length) throw new Error('encodeRideFit: no records');
  const endMs = records[records.length - 1].tMs;
  const rideLaps = laps.length ? laps : [{ startMs: startTimeMs, endMs }];
  const has = (key) => records.some((r) => r[key] != null);
  const w = new Writer();

  // --- file_id (global 0, local 0) ---
  const fileIdFields = [
    { num: 0, type: ENUM }, // type: 4 = activity
    { num: 1, type: UINT16 }, // manufacturer: 255 = development
    { num: 2, type: UINT16 }, // product
    { num: 3, type: UINT32Z }, // serial_number
    { num: 4, type: UINT32 }, // time_created
  ];
  w.definition(0, 0, fileIdFields);
  w.data(0, fileIdFields, [4, 255, 0, (Math.round(startTimeMs / 1000) >>> 0) || 1, toFitTs(startTimeMs)]);

  // --- record (global 20, local 1), only fields present in the ride ---
  const recFields = [{ num: 253, type: UINT32, get: (r) => toFitTs(r.tMs) }];
  if (has('power')) recFields.push({ num: 7, type: UINT16, get: (r) => r.power });
  if (has('hr')) recFields.push({ num: 3, type: UINT8, get: (r) => r.hr });
  if (has('cadence')) recFields.push({ num: 4, type: UINT8, get: (r) => r.cadence });
  if (has('speedKmh')) recFields.push({ num: 6, type: UINT16, get: (r) => (r.speedKmh == null ? null : (r.speedKmh / 3.6) * 1000) }); // m/s * 1000
  if (has('distanceM')) recFields.push({ num: 5, type: UINT32, get: (r) => (r.distanceM == null ? null : r.distanceM * 100) }); // m * 100
  w.definition(1, 20, recFields);
  for (const r of records) w.data(1, recFields, recFields.map((f) => f.get(r)));

  // --- lap (global 19, local 2) ---
  const lapFields = [
    { num: 254, type: UINT16 }, // message_index
    { num: 253, type: UINT32 }, // timestamp (lap end)
    { num: 0, type: ENUM }, // event: 9 = lap
    { num: 1, type: ENUM }, // event_type: 1 = stop
    { num: 2, type: UINT32 }, // start_time
    { num: 7, type: UINT32 }, // total_elapsed_time (s * 1000)
    { num: 8, type: UINT32 }, // total_timer_time (s * 1000)
  ];
  if (has('power')) lapFields.push({ num: 19, type: UINT16 }, { num: 20, type: UINT16 }); // avg/max power
  if (has('hr')) lapFields.push({ num: 15, type: UINT8 }); // avg_heart_rate
  if (has('cadence')) lapFields.push({ num: 17, type: UINT8 }); // avg_cadence
  w.definition(2, 19, lapFields);
  rideLaps.forEach((lap, i) => {
    const last = i === rideLaps.length - 1;
    const inLap = records.filter((r) => r.tMs >= lap.startMs && (last ? r.tMs <= lap.endMs : r.tMs < lap.endMs));
    const durMs = lap.endMs - lap.startMs;
    const values = [i, toFitTs(lap.endMs), 9, 1, toFitTs(lap.startMs), durMs, durMs];
    if (has('power')) values.push(avg(inLap.map((r) => r.power)), max(inLap.map((r) => r.power)));
    if (has('hr')) values.push(avg(inLap.map((r) => r.hr)));
    if (has('cadence')) values.push(avg(inLap.map((r) => r.cadence)));
    w.data(2, lapFields, values);
  });

  // --- session (global 18, local 3) ---
  const powers = records.map((r) => r.power ?? 0);
  const durationS = totals.durationSec ?? (endMs - startTimeMs) / 1000;
  const np = has('power') ? (totals.np ?? normalizedPower(powers)) : null;
  const sessionFields = [
    { num: 254, type: UINT16 }, // message_index
    { num: 253, type: UINT32 }, // timestamp
    { num: 0, type: ENUM }, // event: 8 = session
    { num: 1, type: ENUM }, // event_type: 1 = stop
    { num: 2, type: UINT32 }, // start_time
    { num: 5, type: ENUM }, // sport: 2 = cycling
    { num: 6, type: ENUM }, // sub_sport: 6 = indoor_cycling
    { num: 7, type: UINT32 }, // total_elapsed_time (s * 1000)
    { num: 8, type: UINT32 }, // total_timer_time (s * 1000)
    { num: 25, type: UINT16 }, // first_lap_index
    { num: 26, type: UINT16 }, // num_laps
  ];
  const sessionValues = [
    0, toFitTs(endMs), 8, 1, toFitTs(startTimeMs), 2, 6,
    ((endMs - startTimeMs) / 1000) * 1000, durationS * 1000, 0, rideLaps.length,
  ];
  if (has('power')) {
    sessionFields.push(
      { num: 20, type: UINT16 }, // avg_power
      { num: 21, type: UINT16 }, // max_power
      { num: 34, type: UINT16 }, // normalized_power
      { num: 11, type: UINT16 }, // total_calories (kJ ~ kcal for cycling)
    );
    sessionValues.push(avg(records.map((r) => r.power)), max(records.map((r) => r.power)), np, totals.kj ?? kilojoules(records));
  }
  if (has('hr')) {
    sessionFields.push({ num: 16, type: UINT8 }); // avg_heart_rate
    sessionValues.push(avg(records.map((r) => r.hr)));
  }
  if (has('cadence')) {
    sessionFields.push({ num: 18, type: UINT8 }); // avg_cadence
    sessionValues.push(avg(records.map((r) => r.cadence)));
  }
  if (has('distanceM')) {
    sessionFields.push({ num: 9, type: UINT32 }); // total_distance (m * 100)
    sessionValues.push((totals.distanceM ?? records[records.length - 1].distanceM ?? 0) * 100);
  }
  w.definition(3, 18, sessionFields);
  w.data(3, sessionFields, sessionValues);

  // --- activity (global 34, local 4) ---
  const actFields = [
    { num: 253, type: UINT32 }, // timestamp
    { num: 0, type: UINT32 }, // total_timer_time (s * 1000)
    { num: 1, type: UINT16 }, // num_sessions
    { num: 2, type: ENUM }, // type: 0 = manual
    { num: 3, type: ENUM }, // event: 26 = activity
    { num: 4, type: ENUM }, // event_type: 1 = stop
  ];
  w.definition(4, 34, actFields);
  w.data(4, actFields, [toFitTs(endMs), durationS * 1000, 1, 0, 26, 1]);

  // --- assemble: 14-byte header + data + file CRC ---
  const data = w.bytes;
  const header = new Writer();
  header.u8(14); // header size
  header.u8(0x20); // protocol version 2.0
  header.u16(2194); // profile version 21.94
  header.u32(data.length);
  for (const c of '.FIT') header.u8(c.charCodeAt(0));
  header.u16(crc16(header.bytes.slice(0, 12)));

  const out = new Uint8Array(14 + data.length + 2);
  out.set(header.bytes, 0);
  out.set(data, 14);
  const fileCrc = crc16(out.subarray(0, 14 + data.length));
  out[out.length - 2] = fileCrc & 0xff;
  out[out.length - 1] = fileCrc >>> 8;
  return out;
}
