// Self-test for web/bike/workouts.js + metrics.js. Run: node web/bike/selftest-formats.mjs
import { readFile, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  parseZwo, parseErgMrc, toSteps, workoutStats, rampTest, rampTestFtp, serializeZwo,
} from './workouts.js';
import { RideMetrics, WBal, zoneOf, powerZones, smooth3s } from './metrics.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const WORKOUTS_DIR = join(HERE, '..', '..', 'data', 'bike', 'workouts');

let failures = 0;
let passes = 0;
function check(label, cond) {
  if (cond) {
    passes += 1;
  } else {
    failures += 1;
    console.error(`FAIL: ${label}`);
  }
}
function near(a, b, tol) {
  return Math.abs(a - b) <= tol;
}

// --- parseZwo on a committed file ---
const zwoText = await readFile(join(WORKOUTS_DIR, '2x20-sweet-spot.zwo'), 'utf8');
const sweetSpot = parseZwo(zwoText);
check('zwo name', sweetSpot.name === '2x20 Sweet Spot');
check('zwo sportType', sweetSpot.sportType === 'bike');
check('zwo tags', sweetSpot.tags.length === 2 && sweetSpot.tags[0] === 'sweetspot');
check('zwo segment count', sweetSpot.segments.length === 3);
check('zwo kinds', sweetSpot.segments.map((s) => s.kind).join(',') === 'warmup,intervals,cooldown');
const totalDuration = sweetSpot.segments.reduce((a, s) => a + s.duration, 0);
check('zwo total duration 4200', totalDuration === 4200);
check('zwo warmup powers', sweetSpot.segments[0].powerLow === 0.4 && sweetSpot.segments[0].powerHigh === 0.75);
check('zwo intervals attrs', sweetSpot.segments[1].repeat === 2 && sweetSpot.segments[1].onPower === 0.9);
check('zwo textevents parsed', sweetSpot.segments[0].textEvents.length === 2
  && sweetSpot.segments[0].textEvents[1].offset === 480);

// --- malformed input throws ---
for (const bad of ['', '<workout_file><workout><Bogus Duration="10"/></workout></workout_file>',
  '<workout_file><workout><SteadyState Power="0.5"/></workout></workout_file>', '<oops/>']) {
  let threw = false;
  try { parseZwo(bad); } catch { threw = true; }
  check(`malformed zwo throws (${bad.slice(0, 30) || 'empty'})`, threw);
}

// --- toSteps: IntervalsT expansion + watts at a given time ---
const steps = toSteps(sweetSpot, 250);
check('steps count 1+4+1', steps.length === 6);
check('steps contiguous', steps.every((s, i) => i === 0 || s.start === steps[i - 1].start + steps[i - 1].duration));
const at = (t) => steps.find((s) => t >= s.start && t < s.start + s.duration);
check('watts during first on-block (t=700)', at(700).kind === 'on' && at(700).powerStartW === Math.round(0.9 * 250));
check('watts during first off-block (t=1900)', at(1900).kind === 'off' && at(1900).powerStartW === Math.round(0.5 * 250));
check('warmup ramp start/end watts', steps[0].powerStartW === 100 && steps[0].powerEndW === Math.round(0.75 * 250));
check('cooldown descends', steps[5].powerStartW > steps[5].powerEndW);
check('zone of on-step is Z3 (0.90 mean)', at(700).zone === zoneOf(0.9).z);
check('textevent lands in containing step (atSec absolute)',
  steps[0].textEvents.some((e) => e.atSec === 480));

// --- freeride/maxeffort have no ERG target ---
const freeSteps = toSteps({
  name: 'x', description: '', sportType: 'bike', tags: [],
  segments: [{ kind: 'freeride', duration: 300, textEvents: [] }],
}, 250);
check('freeride step has null target', freeSteps[0].powerStartW === null && freeSteps[0].zone === null);

// --- parseErgMrc: MRC (percent) ---
const mrc = [
  '[COURSE HEADER]', 'VERSION = 2', 'UNITS = ENGLISH', 'DESCRIPTION = Test MRC',
  'FILE NAME = test.mrc', 'MINUTES PERCENT', '[END COURSE HEADER]',
  '[COURSE DATA]', '0.00\t50', '5.00\t50', '5.00\t100', '10.00\t100', '[END COURSE DATA]',
].join('\n');
const mrcWorkout = parseErgMrc(mrc);
check('mrc name', mrcWorkout.name === 'Test MRC');
check('mrc segments', mrcWorkout.segments.length === 2);
check('mrc steady 300s @0.5', mrcWorkout.segments[0].kind === 'steady'
  && mrcWorkout.segments[0].duration === 300 && mrcWorkout.segments[0].power === 0.5);
check('mrc second block @1.0', mrcWorkout.segments[1].power === 1.0);

// --- parseErgMrc: ERG (absolute watts, ramp) ---
const erg = [
  '[COURSE HEADER]', 'VERSION = 2', 'DESCRIPTION = Test ERG', 'FTP = 200',
  'MINUTES WATTS', '[END COURSE HEADER]',
  '[COURSE DATA]', '0 100', '5 200', '[END COURSE DATA]',
].join('\n');
const ergWorkout = parseErgMrc(erg);
check('erg ramp segment', ergWorkout.segments.length === 1 && ergWorkout.segments[0].kind === 'ramp');
check('erg watts to fractions', ergWorkout.segments[0].powerLow === 0.5 && ergWorkout.segments[0].powerHigh === 1.0);
let ergThrew = false;
try { parseErgMrc(erg.replace('FTP = 200\n', '')); } catch { ergThrew = true; }
check('erg without FTP throws', ergThrew);

// --- RideMetrics: constant hour at FTP ---
const constant = new RideMetrics();
for (let t = 0; t < 3600; t += 1) constant.add(t * 1000, { power: 200, hr: 150, cadence: 90 });
check('const NP == 200', near(constant.np, 200, 0.01));
check('const IF == 1.0', near(constant.intensityFactor(200), 1.0, 0.001));
check('const TSS ~ 100', near(constant.tss(200), 100, 0.5));
check('const kJ ~ 720', near(constant.kj, 720, 1));
check('avgHr / avgCadence', constant.avgHr === 150 && constant.avgCadence === 90);
check('maxPower', constant.maxPower === 200);

// --- RideMetrics: variable ride has NP > avg ---
const variable = new RideMetrics();
for (let t = 0; t < 3600; t += 1) {
  variable.add(t * 1000, { power: Math.floor(t / 300) % 2 === 0 ? 300 : 100 });
}
check('variable avg == 200', near(variable.avgPower, 200, 1));
check('variable NP > avg', variable.np > variable.avgPower + 20);

// --- NP before 30s of data falls back to avg ---
const short = new RideMetrics();
for (let t = 0; t < 10; t += 1) short.add(t * 1000, { power: 250 });
check('short ride NP falls back to avg', short.np === 250);

// --- WBal ---
const wbal = new WBal({ cp: 250, wPrimeJ: 20000 });
for (let t = 0; t <= 60; t += 1) wbal.add(t * 1000, 350);
const afterBurn = wbal.value;
check('WBal depletes above CP (~14000 J)', near(afterBurn, 14000, 200));
for (let t = 61; t <= 300; t += 1) wbal.add(t * 1000, 150);
check('WBal recovers below CP', wbal.value > afterBurn + 2000 && wbal.value <= 20000);
const drained = new WBal({ cp: 200, wPrimeJ: 20000 });
for (let t = 0; t <= 600; t += 1) drained.add(t * 1000, 400);
check('WBal clamps at 0', drained.value === 0 && drained.pct === 0);

// --- zones ---
check('zoneOf(0.75) is Z2', zoneOf(0.75).z === 2);
check('zoneOf(2.0) is Z7', zoneOf(2.0).z === 7);
check('powerZones watts', powerZones(200)[3].loW === 182 && powerZones(200)[3].hiW === 210);
const sm = smooth3s();
sm(100); sm(200);
check('smooth3s rolling mean', sm(300) === 200);

// --- ramp test ---
check('rampTestFtp(320) == 240', rampTestFtp(320) === 240);
const ramp = rampTest(200);
check('ramp test: warmup + 20 steps', ramp.segments.length === 21 && ramp.segments[0].kind === 'warmup');
check('ramp first step 46%', ramp.segments[1].power === 0.46 && ramp.segments[1].duration === 60);
check('ramp step increment 6%', near(ramp.segments[2].power - ramp.segments[1].power, 0.06, 1e-9));
check('ramp step announces watts', ramp.segments[1].textEvents[0].message.includes('92 W'));

// --- serialize -> parse round-trip ---
const rampStats = workoutStats(ramp, 200);
const roundTrip = parseZwo(serializeZwo(sweetSpot));
check('round-trip name/description', roundTrip.name === sweetSpot.name
  && roundTrip.description === sweetSpot.description);
check('round-trip segments identical', JSON.stringify(roundTrip.segments) === JSON.stringify(sweetSpot.segments));
const rampRoundTrip = parseZwo(serializeZwo(ramp));
check('round-trip preserves stats', near(workoutStats(rampRoundTrip, 200).tss, rampStats.tss, 0.01));

// --- index.json matches recomputed stats for every committed workout ---
const index = JSON.parse(await readFile(join(WORKOUTS_DIR, 'index.json'), 'utf8'));
const zwoFiles = (await readdir(WORKOUTS_DIR)).filter((f) => f.endsWith('.zwo')).sort();
check('index covers all zwo files', index.workouts.length === zwoFiles.length
  && index.workouts.every((w, i) => w.file === zwoFiles[i]));
for (const entry of index.workouts) {
  const workout = parseZwo(await readFile(join(WORKOUTS_DIR, entry.file), 'utf8'));
  const stats = workoutStats(workout, 200);
  check(`${entry.file}: name matches`, entry.name === workout.name);
  check(`${entry.file}: duration ${entry.durationSec}`, entry.durationSec === stats.durationSec);
  check(`${entry.file}: tss ${entry.tss}`, near(entry.tss, stats.tss, 0.05));
  check(`${entry.file}: if ${entry.if}`, near(entry.if, stats.if_, 0.0005));
}

console.log(`${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
