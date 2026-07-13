// ZWO / ERG / MRC workout formats: parse, serialize, expand to executable
// steps, and estimate stats. Pure logic, node-compatible (no DOM), so the
// XML parser below is hand-rolled: node has no DOMParser and the app has no
// build step.
// ZWO reference: github.com/h4l/zwift-workout-file-reference

import { RideMetrics, zoneOf } from './metrics.js';

// --- minimal recursive-descent XML parser -----------------------------------

const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };

function decodeEntities(s) {
  if (!s.includes('&')) return s;
  let out = '';
  let i = 0;
  while (i < s.length) {
    const amp = s.indexOf('&', i);
    if (amp < 0) return out + s.slice(i);
    out += s.slice(i, amp);
    const semi = s.indexOf(';', amp);
    const name = semi > amp ? s.slice(amp + 1, semi) : '';
    if (name in ENTITIES) {
      out += ENTITIES[name];
      i = semi + 1;
    } else if (name[0] === '#') {
      const code = name[1] === 'x' || name[1] === 'X'
        ? parseInt(name.slice(2), 16)
        : parseInt(name.slice(1), 10);
      out += Number.isNaN(code) ? '&' : String.fromCodePoint(code);
      i = Number.isNaN(code) ? amp + 1 : semi + 1;
    } else {
      out += '&';
      i = amp + 1;
    }
  }
  return out;
}

// Returns {tag, attrs, children, text} for the root element.
function parseXml(src) {
  let i = 0;
  const fail = (msg) => {
    throw new Error(`XML parse error: ${msg} near "${src.slice(i, i + 40)}"`);
  };
  const skipWs = () => {
    while (i < src.length && ' \t\r\n'.includes(src[i])) i += 1;
  };
  const skipMisc = () => {
    // Prolog, comments, doctype — irrelevant for us, skip them all.
    for (;;) {
      skipWs();
      if (src.startsWith('<?', i)) {
        const end = src.indexOf('?>', i);
        if (end < 0) fail('unterminated <? ... ?>');
        i = end + 2;
      } else if (src.startsWith('<!--', i)) {
        const end = src.indexOf('-->', i);
        if (end < 0) fail('unterminated comment');
        i = end + 3;
      } else if (src.startsWith('<!', i)) {
        const end = src.indexOf('>', i);
        if (end < 0) fail('unterminated <! ... >');
        i = end + 1;
      } else {
        return;
      }
    }
  };
  const readName = () => {
    const start = i;
    while (i < src.length && !' \t\r\n/>='.includes(src[i]) && src[i] !== '<') i += 1;
    if (i === start) fail('expected a name');
    return src.slice(start, i);
  };
  const parseElement = () => {
    if (src[i] !== '<') fail("expected '<'");
    i += 1;
    const tag = readName();
    const attrs = {};
    for (;;) {
      skipWs();
      if (src.startsWith('/>', i)) {
        i += 2;
        return { tag, attrs, children: [], text: '' };
      }
      if (src[i] === '>') {
        i += 1;
        break;
      }
      if (i >= src.length) fail(`unterminated <${tag}> tag`);
      const name = readName();
      skipWs();
      let value = '';
      if (src[i] === '=') {
        i += 1;
        skipWs();
        const quote = src[i];
        if (quote !== '"' && quote !== "'") fail(`attribute ${name} value must be quoted`);
        const end = src.indexOf(quote, i + 1);
        if (end < 0) fail(`unterminated value for attribute ${name}`);
        value = decodeEntities(src.slice(i + 1, end));
        i = end + 1;
      }
      attrs[name] = value;
    }
    const children = [];
    let text = '';
    for (;;) {
      if (i >= src.length) fail(`missing closing tag for <${tag}>`);
      if (src.startsWith('</', i)) {
        i += 2;
        const close = readName();
        if (close !== tag) fail(`mismatched </${close}>, expected </${tag}>`);
        skipWs();
        if (src[i] !== '>') fail(`malformed closing tag </${close}>`);
        i += 1;
        return { tag, attrs, children, text: text.trim() };
      }
      if (src.startsWith('<!--', i)) {
        const end = src.indexOf('-->', i);
        if (end < 0) fail('unterminated comment');
        i = end + 3;
        continue;
      }
      if (src[i] === '<') {
        children.push(parseElement());
        continue;
      }
      const lt = src.indexOf('<', i);
      if (lt < 0) fail(`missing closing tag for <${tag}>`);
      text += decodeEntities(src.slice(i, lt));
      i = lt;
    }
  };

  skipMisc();
  if (i >= src.length) fail('no root element found');
  const root = parseElement();
  return root;
}

// --- ZWO parsing -------------------------------------------------------------

function loweredAttrs(node) {
  const out = {};
  for (const [key, value] of Object.entries(node.attrs)) out[key.toLowerCase()] = value;
  return out;
}

function num(attrs, name, tag, { required = false, fallback = undefined } = {}) {
  const raw = attrs[name.toLowerCase()];
  if (raw === undefined || raw === '') {
    if (required) throw new Error(`<${tag}> is missing required attribute ${name}`);
    return fallback;
  }
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error(`<${tag}> attribute ${name}="${raw}" is not a number`);
  return value;
}

function parseTextEvents(node) {
  const events = [];
  for (const child of node.children) {
    if (child.tag.toLowerCase() !== 'textevent') continue;
    const attrs = loweredAttrs(child);
    // Real-world files sometimes carry the "mssage" typo — accept it.
    const message = attrs.message ?? attrs.mssage ?? '';
    events.push({ offset: num(attrs, 'timeoffset', 'textevent', { fallback: 0 }), message });
  }
  return events;
}

function parseSegment(node) {
  const tag = node.tag;
  const attrs = loweredAttrs(node);
  const textEvents = parseTextEvents(node);
  const cadence = num(attrs, 'Cadence', tag);
  switch (tag.toLowerCase()) {
    case 'warmup':
    case 'cooldown':
    case 'ramp': {
      const kind = { warmup: 'warmup', cooldown: 'cooldown', ramp: 'ramp' }[tag.toLowerCase()];
      // Note the Zwift quirk: in Cooldown files PowerLow holds the START
      // (higher) power and PowerHigh the end. We keep attribute semantics
      // as-written: powerLow is always the power at t=0 of the block.
      return {
        kind,
        duration: num(attrs, 'Duration', tag, { required: true }),
        powerLow: num(attrs, 'PowerLow', tag, { required: true }),
        powerHigh: num(attrs, 'PowerHigh', tag, { required: true }),
        cadence,
        textEvents,
      };
    }
    case 'steadystate':
      return {
        kind: 'steady',
        duration: num(attrs, 'Duration', tag, { required: true }),
        power: num(attrs, 'Power', tag, { required: true }),
        cadence,
        textEvents,
      };
    case 'intervalst': {
      const repeat = num(attrs, 'Repeat', tag, { required: true });
      const onDuration = num(attrs, 'OnDuration', tag, { required: true });
      const offDuration = num(attrs, 'OffDuration', tag, { required: true });
      return {
        kind: 'intervals',
        repeat,
        onDuration,
        offDuration,
        onPower: num(attrs, 'OnPower', tag, { required: true }),
        offPower: num(attrs, 'OffPower', tag, { required: true }),
        duration: repeat * (onDuration + offDuration),
        cadence,
        cadenceResting: num(attrs, 'CadenceResting', tag),
        textEvents,
      };
    }
    case 'freeride':
      return { kind: 'freeride', duration: num(attrs, 'Duration', tag, { required: true }), textEvents };
    case 'maxeffort':
      return { kind: 'maxeffort', duration: num(attrs, 'Duration', tag, { required: true }), textEvents };
    default:
      throw new Error(`Unknown workout block <${tag}>`);
  }
}

export function parseZwo(xmlString) {
  if (typeof xmlString !== 'string' || !xmlString.trim()) {
    throw new Error('parseZwo: empty input');
  }
  const root = parseXml(xmlString);
  if (root.tag !== 'workout_file') {
    throw new Error(`parseZwo: expected <workout_file> root, got <${root.tag}>`);
  }
  const childText = (tag) => root.children.find((c) => c.tag === tag)?.text ?? '';
  const tagsNode = root.children.find((c) => c.tag === 'tags');
  const tags = (tagsNode?.children ?? [])
    .filter((c) => c.tag === 'tag')
    .map((c) => loweredAttrs(c).name ?? '')
    .filter(Boolean);
  const workoutNode = root.children.find((c) => c.tag === 'workout');
  if (!workoutNode) throw new Error('parseZwo: missing <workout> element');
  return {
    name: childText('name'),
    description: childText('description'),
    sportType: childText('sportType') || 'bike',
    tags,
    segments: workoutNode.children.map(parseSegment),
  };
}

// --- ERG / MRC parsing --------------------------------------------------------

export function parseErgMrc(text) {
  if (typeof text !== 'string' || !text.trim()) throw new Error('parseErgMrc: empty input');
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
  const header = {};
  const rows = [];
  let units = null; // 'watts' | 'percent'
  let section = null;
  for (const line of lines) {
    const upper = line.toUpperCase();
    if (upper.startsWith('[')) {
      if (upper === '[COURSE HEADER]') section = 'header';
      else if (upper === '[COURSE DATA]') section = 'data';
      else section = null;
      continue;
    }
    if (section === 'header') {
      const eq = line.indexOf('=');
      if (eq >= 0) {
        header[line.slice(0, eq).trim().toUpperCase()] = line.slice(eq + 1).trim();
      } else if (upper.includes('MINUTES')) {
        units = upper.includes('PERCENT') ? 'percent' : 'watts';
      }
    } else if (section === 'data') {
      const parts = line.split(/[\s\t]+/).map(Number);
      if (parts.length < 2 || parts.some(Number.isNaN)) {
        throw new Error(`parseErgMrc: bad data row "${line}"`);
      }
      rows.push(parts);
    }
  }
  if (!units) throw new Error('parseErgMrc: missing MINUTES WATTS/PERCENT column header');
  if (rows.length < 2) throw new Error('parseErgMrc: need at least two data rows');
  const ftp = Number(header.FTP);
  if (units === 'watts' && !(ftp > 0)) {
    throw new Error('parseErgMrc: ERG file (absolute watts) requires FTP= in [COURSE HEADER]');
  }
  const toFraction = (v) => (units === 'percent' ? v / 100 : v / ftp);

  const segments = [];
  for (let k = 0; k < rows.length - 1; k += 1) {
    const [t1, v1] = rows[k];
    const [t2, v2] = rows[k + 1];
    const duration = Math.round((t2 - t1) * 60);
    if (duration <= 0) continue; // repeated timestamp = instantaneous jump, not a segment
    const p1 = toFraction(v1);
    const p2 = toFraction(v2);
    if (p1 === p2) {
      segments.push({ kind: 'steady', duration, power: p1, textEvents: [] });
    } else {
      segments.push({ kind: 'ramp', duration, powerLow: p1, powerHigh: p2, textEvents: [] });
    }
  }
  return {
    name: header.DESCRIPTION || header['FILE NAME'] || 'Imported workout',
    description: header.DESCRIPTION || '',
    sportType: 'bike',
    tags: [],
    segments,
  };
}

// --- expansion to executable steps --------------------------------------------

function makeStep(start, duration, kind, startFrac, endFrac, ftp, cadence) {
  const hasTarget = startFrac !== null;
  const meanFrac = hasTarget ? (startFrac + endFrac) / 2 : null;
  return {
    start,
    duration,
    kind,
    powerStartW: hasTarget ? Math.round(startFrac * ftp) : null,
    powerEndW: hasTarget ? Math.round(endFrac * ftp) : null,
    ...(cadence !== undefined && cadence !== null ? { cadence } : {}),
    zone: hasTarget ? zoneOf(meanFrac).z : null,
    textEvents: [],
  };
}

export function toSteps(workout, ftp) {
  const steps = [];
  let t = 0;
  for (const seg of workout.segments) {
    const segStart = t;
    const first = steps.length;
    switch (seg.kind) {
      case 'warmup':
      case 'cooldown':
      case 'ramp':
        steps.push(makeStep(t, seg.duration, seg.kind, seg.powerLow, seg.powerHigh, ftp, seg.cadence));
        t += seg.duration;
        break;
      case 'steady':
        steps.push(makeStep(t, seg.duration, 'steady', seg.power, seg.power, ftp, seg.cadence));
        t += seg.duration;
        break;
      case 'intervals':
        for (let r = 0; r < seg.repeat; r += 1) {
          steps.push(makeStep(t, seg.onDuration, 'on', seg.onPower, seg.onPower, ftp, seg.cadence));
          t += seg.onDuration;
          steps.push(makeStep(t, seg.offDuration, 'off', seg.offPower, seg.offPower, ftp, seg.cadenceResting));
          t += seg.offDuration;
        }
        break;
      case 'freeride':
      case 'maxeffort':
        steps.push(makeStep(t, seg.duration, seg.kind, null, null, ftp));
        t += seg.duration;
        break;
      default:
        throw new Error(`toSteps: unknown segment kind "${seg.kind}"`);
    }
    for (const ev of seg.textEvents ?? []) {
      const atSec = segStart + ev.offset;
      // Attach to the step whose time range contains the event.
      let target = steps[steps.length - 1];
      for (let s = first; s < steps.length; s += 1) {
        if (atSec < steps[s].start + steps[s].duration) {
          target = steps[s];
          break;
        }
      }
      target.textEvents.push({ atSec, message: ev.message });
    }
  }
  return steps;
}

// --- stats estimation ----------------------------------------------------------

// No power target → assume a moderate endurance effort for estimation.
const FREERIDE_FRAC = 0.6;
const MAXEFFORT_FRAC = 1.2;

export function workoutStats(workout, ftp) {
  const steps = toSteps(workout, ftp);
  const metrics = new RideMetrics();
  let durationSec = 0;
  let joules = 0;
  for (const step of steps) {
    const startW = step.powerStartW ?? (step.kind === 'maxeffort' ? MAXEFFORT_FRAC : FREERIDE_FRAC) * ftp;
    const endW = step.powerEndW ?? startW;
    for (let s = 0; s < step.duration; s += 1) {
      const w = startW + (endW - startW) * (s / step.duration);
      metrics.add((durationSec + s) * 1000, { power: w });
      joules += w;
    }
    durationSec += step.duration;
  }
  const np = metrics.np;
  const if_ = ftp > 0 ? np / ftp : 0;
  return {
    durationSec,
    np,
    if_,
    tss: (durationSec / 3600) * if_ * if_ * 100,
    kj: joules / 1000,
  };
}

// --- ramp test ------------------------------------------------------------------

const RAMP_STEP_PCT = 6;
const RAMP_START_PCT = 46;
const RAMP_MAX_STEPS = 20;

export function rampTest(estimatedFtp) {
  const segments = [
    {
      kind: 'warmup',
      duration: 300,
      powerLow: 0.4,
      powerHigh: 0.6,
      textEvents: [{ offset: 10, message: 'Ramp test: spin easy, one-minute steps begin soon.' }],
    },
  ];
  for (let k = 0; k < RAMP_MAX_STEPS; k += 1) {
    // Integer percent math keeps fractions clean (0.52, not 0.52000000000000005).
    const frac = (RAMP_START_PCT + RAMP_STEP_PCT * k) / 100;
    const watts = Math.round(frac * estimatedFtp);
    segments.push({
      kind: 'steady',
      duration: 60,
      power: frac,
      textEvents: [{ offset: 0, message: `Step ${k + 1}: ${watts} W` }],
    });
  }
  return {
    name: 'Ramp Test',
    description:
      'One-minute steps rising until you cannot hold the target. '
      + 'Stop pedaling when you blow up — your FTP is estimated from the best full minute.',
    sportType: 'bike',
    tags: ['test'],
    segments,
  };
}

export function rampTestFtp(bestOneMinutePower) {
  return Math.round(0.75 * bestOneMinutePower);
}

// --- serialization ----------------------------------------------------------------

function escapeXml(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function attrStr(pairs) {
  return pairs
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => ` ${k}="${escapeXml(v)}"`)
    .join('');
}

function serializeSegment(seg) {
  const tagFor = {
    warmup: 'Warmup',
    cooldown: 'Cooldown',
    ramp: 'Ramp',
    steady: 'SteadyState',
    intervals: 'IntervalsT',
    freeride: 'FreeRide',
    maxeffort: 'MaxEffort',
  };
  const tag = tagFor[seg.kind];
  if (!tag) throw new Error(`serializeZwo: unknown segment kind "${seg.kind}"`);
  let pairs;
  switch (seg.kind) {
    case 'warmup':
    case 'cooldown':
    case 'ramp':
      pairs = [
        ['Duration', seg.duration],
        ['PowerLow', seg.powerLow],
        ['PowerHigh', seg.powerHigh],
        ['Cadence', seg.cadence],
      ];
      break;
    case 'steady':
      pairs = [
        ['Duration', seg.duration],
        ['Power', seg.power],
        ['Cadence', seg.cadence],
      ];
      break;
    case 'intervals':
      pairs = [
        ['Repeat', seg.repeat],
        ['OnDuration', seg.onDuration],
        ['OffDuration', seg.offDuration],
        ['OnPower', seg.onPower],
        ['OffPower', seg.offPower],
        ['Cadence', seg.cadence],
        ['CadenceResting', seg.cadenceResting],
      ];
      break;
    default:
      pairs = [['Duration', seg.duration]];
  }
  const events = seg.textEvents ?? [];
  if (!events.length) return `        <${tag}${attrStr(pairs)}/>`;
  const inner = events
    .map((ev) => `            <textevent${attrStr([['timeoffset', ev.offset], ['message', ev.message]])}/>`)
    .join('\n');
  return `        <${tag}${attrStr(pairs)}>\n${inner}\n        </${tag}>`;
}

export function serializeZwo(workout) {
  const tags = (workout.tags ?? [])
    .map((t) => `        <tag${attrStr([['name', t]])}/>`)
    .join('\n');
  return [
    '<workout_file>',
    '    <author>PaceForge</author>',
    `    <name>${escapeXml(workout.name ?? '')}</name>`,
    `    <description>${escapeXml(workout.description ?? '')}</description>`,
    `    <sportType>${escapeXml(workout.sportType ?? 'bike')}</sportType>`,
    tags ? `    <tags>\n${tags}\n    </tags>` : '    <tags/>',
    '    <workout>',
    workout.segments.map(serializeSegment).join('\n'),
    '    </workout>',
    '</workout_file>',
    '',
  ].join('\n');
}
