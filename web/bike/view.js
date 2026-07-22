// Bike tab UI: home (devices / athlete / workouts / history) → player → post-ride.
// Host helpers (escHtml, toast, loadJSON, gh* …) are injected by index.html via
// renderBikeTab(page, host) so this module stays testable and index.html stays thin.
import { FtmsTrainer } from './trainer.js';
import { MockTrainer, MockHeartRate } from './mock-trainer.js';
import { HeartRateMonitor } from './hr.js';
import { ZwiftRideControls } from './zwift-ride.js';
import { parseZwo, parseErgMrc, toSteps, workoutStats, rampTest, rampTestFtp } from './workouts.js';
import { COGGAN_ZONES, powerZones } from './metrics.js';
import { RideRecorder } from './recorder.js';
import { encodeRideFit } from './fit.js';
import { uploadIntervalsIcu, uploadStrava } from './upload.js';
import { RidePlayer } from './player.js';
import { NS } from './ns.js';

const PROFILE_KEY = 'pf-bike-profile' + NS;
const PENDING_KEY = 'pf-bike-rides-pending' + NS;
const IMPORTS_KEY = 'pf-bike-imports' + NS;
// Upload tokens live ONLY in sessionStorage: cleared when the browser session
// ends, never disk-backed.
const INTERVALS_KEY = 'pf-bike-intervals-key' + NS;
const STRAVA_KEY = 'pf-bike-strava-token' + NS;
// purge tokens persisted by older versions
try { localStorage.removeItem(INTERVALS_KEY); localStorage.removeItem(STRAVA_KEY); } catch {}

let H = null; // host helpers, set on every renderBikeTab call

const S = {
  screen: 'home',
  page: null,
  demo: false,
  trainer: null,
  hrm: null,
  ride: null,          // Zwift Ride controls
  profile: null,
  player: null,
  mode: 'workout',     // 'workout' | 'ramp' | 'freeride'
  workoutName: '',
  steps: [],
  gear: 12,
  result: null,        // { startTimeMs, data:{records,laps,summary}, ftpUsed, best60, recovered }
  trace: [],           // player actual-power polyline points
  ui: {},              // live element refs for the player screen
  wakeLock: null,
  keyHandler: null,
  rideBtnHandler: null,
};

const zwoCache = new Map(); // file → parsed workout

export function initBike(api) {
  api.renderBikeTab = renderBikeTab;
}

async function renderBikeTab(page, host) {
  H = host;
  S.page = page;
  await draw();
}

async function draw() {
  if (!S.page) return;
  if (S.screen === 'player') renderPlayer();
  else if (S.screen === 'post') renderPost();
  else await renderHome();
}

// ── small helpers ──────────────────────────────────────

function ls(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function lsSet(key, v) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch {}
}

function fmtDur(sec) {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function zoneChip(label, color) {
  return `<span class="chip" style="--accent:${color};--accent-d:color-mix(in srgb, ${color} 15%, transparent)">${H.escHtml(label)}</span>`;
}

function ftp() { return S.profile?.ftp || 200; }

async function loadProfile() {
  const base = await H.loadJSON('bike/profile.json').catch(() => ({ ftp: 200, wprime_j: 20000 }));
  S.profile = { ...base, ...ls(PROFILE_KEY, {}) };
  return S.profile;
}

// Power-profile SVG shapes for a step list: one zone-colored trapezoid per step.
function profileShapes(steps, ftpW, W, Hh) {
  if (!steps.length) return { shapes: '', total: 0, maxW: ftpW * 1.2 };
  const last = steps[steps.length - 1];
  const total = last.start + last.duration;
  let maxW = ftpW * 1.2;
  for (const st of steps) maxW = Math.max(maxW, st.powerStartW ?? 0, st.powerEndW ?? 0);
  const x = t => (t / total) * W;
  const y = w => Hh - Math.min(w / maxW, 1) * (Hh - 2);
  let shapes = '';
  for (const st of steps) {
    const x1 = x(st.start), x2 = x(st.start + st.duration);
    if (st.powerStartW == null) {
      // free ride / max effort: neutral block at ~60% FTP height
      shapes += `<rect x="${x1.toFixed(1)}" y="${y(ftpW * 0.6).toFixed(1)}" width="${(x2 - x1).toFixed(1)}" height="${(Hh - y(ftpW * 0.6)).toFixed(1)}" fill="#5E6678" opacity=".45"/>`;
    } else {
      const color = COGGAN_ZONES[(st.zone ?? 1) - 1]?.color || '#5E6678';
      shapes += `<polygon points="${x1.toFixed(1)},${y(st.powerStartW).toFixed(1)} ${x2.toFixed(1)},${y(st.powerEndW).toFixed(1)} ${x2.toFixed(1)},${Hh} ${x1.toFixed(1)},${Hh}" fill="${color}" opacity=".85"/>`;
    }
  }
  return { shapes, total, maxW };
}

// ═══════════ HOME ═══════════

// ponytail: 3-rule suggestion — per-zone progression levels once real ride history exists
function suggestNext(rides, workouts) {
  if (!workouts.length) return null;
  const pick = name => workouts.find(w => w.name === name) || workouts[0];
  const last = rides[0];
  if (!last) return { w: pick('2x20 Sweet Spot'), why: 'First ride — settle in at sweet spot' };
  const weekTss = rides
    .filter(r => r.date && (Date.now() - Date.parse(r.date)) < 7 * 864e5)
    .reduce((s, r) => s + (r.tss || 0), 0);
  if (weekTss > 250) return { w: pick('Recovery 45'), why: `Big week (${Math.round(weekTss)} TSS) — spin easy` };
  if ((last.if || 0) >= 0.83 || (last.tss || 0) >= 70) return { w: pick('Endurance 90'), why: 'Last ride was hard — aerobic day' };
  return { w: pick('4x8 VO2'), why: 'Fresh legs — quality day' };
}

async function renderHome() {
  H.setTopbar('Bike', 'Indoor trainer — workouts, ERG & rides');
  const [profile, index, rides] = await Promise.all([
    loadProfile(),
    H.loadJSON('bike/workouts/index.json').catch(() => ({ workouts: [] })),
    H.loadJSON('bike/rides.json').catch(() => ({ rides: [] })),
  ]);
  const hasBt = !!navigator.bluetooth;
  const recovered = RideRecorder.recover();
  const zones = powerZones(profile.ftp || 200);
  const pending = ls(PENDING_KEY, []);
  const allRides = [...pending.map(r => ({ ...r, pending: true })), ...(rides.rides || []).slice().reverse()].slice(0, 8);
  const imports = ls(IMPORTS_KEY, []);
  const suggestion = suggestNext(allRides, index.workouts || []);

  S.page.innerHTML = `
  ${recovered ? `
  <div class="banner warn" style="margin-bottom:18px">
    <span class="b-ico">${bikeIcons.alert}</span>
    <div style="flex:1">Unfinished ride found (${recovered.records?.length || 0} samples, started ${new Date(recovered.startTimeMs).toLocaleString()}). Recover it?</div>
    <button class="btn btn-sm btn-primary" id="bk-recover">Recover</button>
    <button class="btn btn-sm btn-outline" id="bk-discard">Discard</button>
  </div>` : ''}
  <div class="dash-grid">
    <div class="card span-6">
      <div class="card-h"><div class="card-title"><span class="ico">${bikeIcons.bt}</span>Devices</div>
        <label class="bk-demo"><input type="checkbox" id="bk-demo" ${S.demo ? 'checked' : ''}> Demo mode</label>
      </div>
      ${hasBt ? '' : `<div class="banner warn" style="margin-bottom:12px"><span class="b-ico">${bikeIcons.alert}</span>Web Bluetooth needs Chrome/Edge on desktop or Android — Demo mode still works.</div>`}
      <div id="bk-devices">${devicesHtml(hasBt)}</div>
    </div>
    <div class="card span-6">
      <div class="card-h"><div class="card-title"><span class="ico">${bikeIcons.gauge}</span>Athlete</div></div>
      <div class="bk-ftp-row">
        <div class="field" style="flex:1;margin:0"><label for="bk-ftp">FTP (watts)</label>
          <input type="number" id="bk-ftp" min="50" max="600" value="${profile.ftp || 200}">
        </div>
        <button class="btn btn-primary" id="bk-ftp-save">Save</button>
      </div>
      <div class="bk-zonebar" role="img" aria-label="Power zones">
        ${zones.map(z => `<div class="bk-zoneseg" style="background:${z.color};flex:${Math.min(z.hi, 1.6) - z.lo || .05}" title="Z${z.z} ${z.name}: ${z.loW}–${z.z === 7 ? '∞' : z.hiW} W"></div>`).join('')}
      </div>
      <div class="bk-zonelegend">${zones.map(z => `<span><i style="background:${z.color}"></i>Z${z.z} ${z.loW}${z.z === 7 ? '+' : '–' + z.hiW}</span>`).join('')}</div>
      <div class="lv"><span class="lv-label">W′ (anaerobic capacity)</span><span class="lv-val">${((profile.wprime_j || 20000) / 1000).toFixed(0)} kJ</span></div>
      <div class="lv"><span class="lv-label">Last FTP change</span><span class="lv-val">${H.escHtml(profile.ftp_history?.length ? `${profile.ftp_history[profile.ftp_history.length - 1].date} (${profile.ftp_history[profile.ftp_history.length - 1].source})` : '—')}</span></div>
    </div>
    <div class="card span-7">
      <div class="card-h"><div class="card-title"><span class="ico">${bikeIcons.bike}</span>Workouts</div>
        <label class="btn btn-sm btn-outline" style="cursor:pointer">Import .zwo/.erg/.mrc<input type="file" id="bk-import" accept=".zwo,.erg,.mrc" hidden></label>
      </div>
      <div class="divlist">
        ${suggestion ? `
        <div class="bk-wo-row" style="background:var(--emerald-g);border-radius:var(--r-sm)">
          <div class="bk-wo-info">
            <div class="act-name">${H.escHtml(suggestion.w.name)}</div>
            <div class="act-meta">${H.escHtml(suggestion.why)} · TSS ${Math.round(suggestion.w.tss)}</div>
          </div>
          ${zoneChip('SUGGESTED', 'var(--emerald)')}
          <button class="btn btn-sm btn-primary" data-start="wo" data-file="${H.escHtml(suggestion.w.file)}" data-name="${H.escHtml(suggestion.w.name)}">Start</button>
        </div>` : ''}
        <div class="bk-wo-row">
          <div class="bk-wo-info"><div class="act-name">Ramp test</div><div class="act-meta">~25 min · one-minute steps to failure · estimates FTP</div></div>
          ${zoneChip('TEST', 'var(--violet)')}
          <button class="btn btn-sm btn-primary" data-start="ramp">Start</button>
        </div>
        <div class="bk-wo-row">
          <div class="bk-wo-info"><div class="act-name">Free ride</div><div class="act-meta">No targets · virtual gears &amp; grade · ERG optional</div></div>
          ${zoneChip('FREE', 'var(--sky)')}
          <button class="btn btn-sm btn-primary" data-start="free">Start</button>
        </div>
        ${(index.workouts || []).map((w, i) => `
        <div class="bk-wo-row">
          <div class="bk-wo-info">
            <div class="act-name">${H.escHtml(w.name)}</div>
            <div class="act-meta">${fmtDur(w.durationSec)} · TSS ${Math.round(w.tss)} · IF ${w.if.toFixed(2)}</div>
          </div>
          <svg class="bk-spark" data-spark="${H.escHtml(w.file)}" viewBox="0 0 120 28" preserveAspectRatio="none" aria-hidden="true"></svg>
          ${zoneChip(w.zones, 'var(--emerald)')}
          <button class="btn btn-sm btn-primary" data-start="wo" data-file="${H.escHtml(w.file)}" data-name="${H.escHtml(w.name)}">Start</button>
        </div>`).join('')}
        ${imports.map((im, i) => `
        <div class="bk-wo-row">
          <div class="bk-wo-info"><div class="act-name">${H.escHtml(im.name)}</div><div class="act-meta">imported ${H.escHtml(im.fmt)}</div></div>
          ${zoneChip('IMPORT', 'var(--amber)')}
          <button class="btn btn-sm btn-primary" data-start="import" data-idx="${i}">Start</button>
        </div>`).join('')}
      </div>
    </div>
    <div class="card span-5">
      <div class="card-h"><div class="card-title"><span class="ico">${bikeIcons.history}</span>Ride history</div></div>
      ${allRides.length ? `<div class="divlist">${allRides.map(r => `
        <div class="bk-hist-row">
          <div style="flex:1;min-width:0">
            <div class="act-name">${H.escHtml(r.workout || 'Ride')}${r.pending ? ' <span class="chip" style="--accent:var(--amber);--accent-d:var(--amber-d)">pending</span>' : ''}</div>
            <div class="act-meta">${H.escHtml((r.date || '').slice(0, 16).replace('T', ' '))}</div>
          </div>
          <div class="act-stat"><div class="v">${fmtDur(r.duration_sec || 0)}</div><div class="l">time</div></div>
          <div class="act-stat"><div class="v">${r.np != null ? Math.round(r.np) : '—'}</div><div class="l">NP</div></div>
          <div class="act-stat"><div class="v">${r.if != null ? Number(r.if).toFixed(2) : '—'}</div><div class="l">IF</div></div>
          <div class="act-stat"><div class="v">${r.tss != null ? Math.round(r.tss) : '—'}</div><div class="l">TSS</div></div>
        </div>`).join('')}</div>`
      : H.emptyState('No rides yet', 'Finished rides land here after "Save to PaceForge".')}
      <div class="card-h" style="margin:20px 0 12px"><div class="card-title"><span class="ico">${bikeIcons.link}</span>Integrations</div></div>
      <div class="field"><label for="bk-icu">intervals.icu API key</label>
        <input type="password" id="bk-icu" class="mono-input" autocomplete="off" value="${H.escHtml(sessionStorage.getItem(INTERVALS_KEY) || '')}">
        <div class="hint">Stored in this browser only. intervals.icu → Settings → Developer.</div>
      </div>
      <div class="field" style="margin-bottom:0"><label for="bk-strava">Strava access token</label>
        <input type="password" id="bk-strava" class="mono-input" autocomplete="off" value="${H.escHtml(sessionStorage.getItem(STRAVA_KEY) || '')}">
        <div class="hint">Needs activity:write scope. Stored locally, never committed.</div>
      </div>
    </div>
  </div>`;

  bindHome(recovered);
  drawSparklines();
}

function devicesHtml(hasBt) {
  const rows = [
    ['trainer', 'Trainer', S.trainer],
    ['hrm', 'Heart rate', S.hrm],
    ['ride', 'Zwift Ride controls', S.ride],
  ];
  return rows.map(([kind, label, dev]) => {
    const on = dev?.connected;
    return `<div class="bk-dev-row">
      <span class="bk-dot ${on ? 'on' : ''}"></span>
      <div style="flex:1"><div class="act-name">${label}</div>
        <div class="act-meta">${on ? H.escHtml(dev.name || 'connected') : 'not connected'}</div></div>
      <button class="btn btn-sm ${on ? 'btn-outline' : 'btn-ghost'}" data-dev="${kind}" ${(!hasBt && !S.demo) || (S.demo && kind !== 'ride') ? 'disabled' : ''}>${on ? 'Disconnect' : 'Connect'}</button>
    </div>`;
  }).join('');
}

function refreshDevices() {
  const box = document.getElementById('bk-devices');
  if (!box || S.screen !== 'home') return;
  box.innerHTML = devicesHtml(!!navigator.bluetooth);
  bindDeviceButtons();
}

function wireDevice(dev) {
  dev.on('connected', refreshDevices);
  dev.on('disconnected', refreshDevices);
  dev.on('status', msg => console.log('[bike]', msg));
  return dev;
}

async function connectDevice(kind, btn) {
  const make = {
    trainer: () => wireDevice(new FtmsTrainer()),
    hrm: () => wireDevice(new HeartRateMonitor()),
    ride: () => wireDevice(new ZwiftRideControls()),
  };
  const cur = S[kind];
  if (cur?.connected) {
    await cur.disconnect().catch(() => {});
    if (!S.demo || kind === 'ride') S[kind] = null;
    refreshDevices();
    return;
  }
  await H.withBusy(btn, 'Pairing…', async () => {
    const dev = make[kind]();
    await dev.connect();
    S[kind] = dev;
    H.toast('ok', 'Connected', H.escHtml(dev.name || kind));
  });
  refreshDevices();
}

function bindDeviceButtons() {
  document.querySelectorAll('[data-dev]').forEach(b =>
    b.addEventListener('click', () => connectDevice(b.dataset.dev, b)));
}

async function setDemo(on) {
  S.demo = on;
  if (on) {
    if (S.trainer?.connected) await S.trainer.disconnect().catch(() => {});
    if (S.hrm?.connected) await S.hrm.disconnect().catch(() => {});
    S.trainer = wireDevice(new MockTrainer());
    S.hrm = wireDevice(new MockHeartRate(S.trainer));
    await S.trainer.connect();
    await S.hrm.connect();
  } else {
    if (S.trainer?.connected) await S.trainer.disconnect().catch(() => {});
    if (S.hrm?.connected) await S.hrm.disconnect().catch(() => {});
    S.trainer = null;
    S.hrm = null;
  }
  refreshDevices();
}

function bindHome(recovered) {
  bindDeviceButtons();
  document.getElementById('bk-demo')?.addEventListener('change', e => setDemo(e.target.checked));

  document.getElementById('bk-ftp-save')?.addEventListener('click', function () {
    const v = Number(document.getElementById('bk-ftp').value);
    if (!(v >= 50 && v <= 600)) return H.toast('err', 'Invalid FTP', 'Enter 50–600 watts.');
    saveProfilePatch({ ftp: v, source: 'manual' }, this);
  });

  document.getElementById('bk-import')?.addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const fmt = file.name.toLowerCase().endsWith('.zwo') ? 'zwo' : 'erg/mrc';
      const wo = fmt === 'zwo' ? parseZwo(text) : parseErgMrc(text);
      const imports = ls(IMPORTS_KEY, []);
      imports.unshift({ name: wo.name || file.name, text, fmt });
      lsSet(IMPORTS_KEY, imports.slice(0, 5));
      const stats = workoutStats(wo, ftp());
      H.toast('ok', 'Workout imported', `${H.escHtml(wo.name || file.name)} — ${fmtDur(stats.durationSec)}, TSS ${Math.round(stats.tss)}`);
      renderHome();
    } catch (err) {
      H.toast('err', 'Import failed', H.escHtml(err.message));
    }
  });

  ;[[INTERVALS_KEY, 'bk-icu'], [STRAVA_KEY, 'bk-strava']].forEach(([key, id]) => {
    document.getElementById(id)?.addEventListener('change', e => {
      try { sessionStorage.setItem(key, e.target.value.trim()); } catch {}
    });
  });

  document.querySelectorAll('[data-start]').forEach(b => b.addEventListener('click', async () => {
    try {
      if (b.dataset.start === 'ramp') await startRide(rampTest(ftp()), 'ramp');
      else if (b.dataset.start === 'free') await startRide(null, 'freeride');
      else if (b.dataset.start === 'import') {
        const im = ls(IMPORTS_KEY, [])[Number(b.dataset.idx)];
        if (!im) return;
        await startRide(im.fmt === 'zwo' ? parseZwo(im.text) : parseErgMrc(im.text), 'workout');
      } else {
        await startRide(await getWorkout(b.dataset.file), 'workout', b.dataset.name);
      }
    } catch (e) { H.toast('err', 'Could not start', H.escHtml(e.message)); }
  }));

  if (recovered) {
    document.getElementById('bk-recover')?.addEventListener('click', () => recoverRide(recovered));
    document.getElementById('bk-discard')?.addEventListener('click', () => {
      new RideRecorder().discard();
      renderHome();
    });
  }
}

async function saveProfilePatch(patch, btn) {
  S.profile = { ...S.profile, ...patch };
  lsSet(PROFILE_KEY, { ftp: S.profile.ftp, wprime_j: S.profile.wprime_j });
  await H.withBusy(btn, 'Saving…', async () => {
    const res = await fetch(`${H.API}/repos/${H.REPO}/actions/workflows/save-bike-profile.yml/dispatches`, {
      method: 'POST', headers: H.JSON_HDR,
      body: JSON.stringify({ inputs: { data: JSON.stringify(patch) } }),
    });
    if (res.status !== 204) throw new Error(`Runner error ${res.status}`);
    H.toast('ok', 'Profile saved', `FTP ${patch.ftp} W saved.`);
  });
}

async function getWorkout(file) {
  if (zwoCache.has(file)) return zwoCache.get(file);
  const res = await fetch('./data/bike/workouts/' + file);
  if (!res.ok) throw new Error('Failed to load ' + file);
  const wo = parseZwo(await res.text());
  zwoCache.set(file, wo);
  return wo;
}

async function drawSparklines() {
  for (const svg of document.querySelectorAll('[data-spark]')) {
    try {
      const wo = await getWorkout(svg.dataset.spark);
      const { shapes } = profileShapes(toSteps(wo, ftp()), ftp(), 120, 28);
      svg.innerHTML = shapes;
    } catch { /* sparkline is decorative */ }
  }
}

// ═══════════ RIDE START / END ═══════════

async function startRide(workout, mode, name) {
  if (!S.trainer?.connected) {
    throw new Error('Connect a trainer first — or flip on Demo mode.');
  }
  const steps = mode === 'freeride' ? [] : toSteps(workout, ftp());
  S.mode = mode;
  S.workoutName = mode === 'freeride' ? 'Free ride' : (name || workout.name || 'Workout');
  S.steps = steps;
  S.gear = S.profile?.virtual_gears?.current_default || 12;
  S.trace = [];
  S.player = new RidePlayer({
    steps, ftp: ftp(), wprimeJ: S.profile?.wprime_j || 20000,
    trainer: S.trainer, hrm: S.hrm, mode,
  });
  if (mode === 'freeride') S.player.erg = false; // free ride starts uncontrolled
  S.player.start();
  S.screen = 'player';
  renderPlayer();
  if (mode === 'freeride') applyGear();
}

function endRide() {
  const player = S.player;
  if (!player) return;
  const data = player.stop();
  detachPlayerUI();
  S.player = null;
  S.result = data ? {
    startTimeMs: player.startTimeMs, data, ftpUsed: player.ftp,
    best60: player.best60, mode: S.mode, workoutName: S.workoutName,
  } : null;
  S.screen = S.result ? 'post' : 'home';
  draw();
}

// Rebuild a summary from a crash checkpoint by rehydrating a recorder.
function recoverRide(saved) {
  const r = new RideRecorder();
  r.running = true;
  r.paused = false;
  r.pausedMs = 0;
  r.pauseStartMs = null;
  r.ftp = saved.ftp || ftp();
  r.startTimeMs = saved.startTimeMs;
  r.records = saved.records || [];
  r.laps = saved.laps || [];
  r.lapStartMs = r.laps.length ? r.laps[r.laps.length - 1].endMs : saved.startTimeMs;
  r.lastSampleMs = r.records.length ? r.records[r.records.length - 1].tMs : saved.startTimeMs;
  r.distanceM = r.records.length ? (r.records[r.records.length - 1].distanceM ?? 0) : 0;
  const data = r.stop();
  if (!data || !data.records.length) {
    H.toast('err', 'Nothing to recover', 'The checkpoint had no samples.');
    new RideRecorder().discard();
    return renderHome();
  }
  S.result = {
    startTimeMs: saved.startTimeMs, data, ftpUsed: r.ftp,
    best60: 0, mode: 'workout', workoutName: 'Recovered ride', recovered: true,
  };
  S.screen = 'post';
  renderPost();
}

// ═══════════ PLAYER ═══════════

function renderPlayer() {
  detachPlayerUI();
  const p = S.player;
  if (!p) { S.screen = 'home'; return renderHome(); }
  H.setTopbar('Bike', S.workoutName);
  const free = S.mode === 'freeride';
  const { shapes, total, maxW } = profileShapes(S.steps, p.ftp, 1000, 180);

  S.page.innerHTML = `
  <div class="bk-player">
    <div class="card" style="padding:14px 16px" ${S.steps.length ? '' : 'hidden'}>
      <svg id="bk-graph" viewBox="0 0 1000 180" preserveAspectRatio="none" aria-label="Workout power profile">
        <g opacity=".9">${shapes}</g>
        <rect id="bk-dim" x="0" y="0" width="0" height="180" fill="#000" opacity=".35"/>
        <polyline id="bk-trace" points="" fill="none" stroke="var(--text)" stroke-width="1.6" opacity=".9"/>
        <line id="bk-cursor" x1="0" x2="0" y1="0" y2="180" stroke="var(--text)" stroke-width="1" opacity=".8"/>
      </svg>
    </div>

    <div class="bk-nums">
      <div class="bk-num"><div class="bk-num-l">Power</div><div class="bk-num-v" id="bk-pwr">0<span class="bk-unit">W</span></div></div>
      <div class="bk-num"><div class="bk-num-l">Target</div><div class="bk-num-v" id="bk-tgt">—</div></div>
      <div class="bk-num"><div class="bk-num-l">Interval</div><div class="bk-num-v" id="bk-int">—</div></div>
      <div class="bk-num"><div class="bk-num-l">Elapsed · Left</div><div class="bk-num-v bk-num-sm" id="bk-time">0:00</div></div>
    </div>

    <div class="bk-subnums">
      <div><span class="bk-sub-l">Cadence</span><span class="bk-sub-v" id="bk-cad">—</span></div>
      <div><span class="bk-sub-l">HR</span><span class="bk-sub-v" id="bk-hr">—</span></div>
      <div><span class="bk-sub-l">NP</span><span class="bk-sub-v" id="bk-np">0</span></div>
      <div><span class="bk-sub-l">IF</span><span class="bk-sub-v" id="bk-if">0.00</span></div>
      <div><span class="bk-sub-l">TSS</span><span class="bk-sub-v" id="bk-tss">0</span></div>
      <div><span class="bk-sub-l">kJ</span><span class="bk-sub-v" id="bk-kj">0</span></div>
      <div class="bk-wbal-box"><span class="bk-sub-l">W′bal</span>
        <span class="bk-wbal" role="img" aria-label="W prime balance"><i id="bk-wbal-fill"></i></span>
        <span class="bk-sub-v" id="bk-wbal-v">100%</span>
      </div>
      ${free ? `<div><span class="bk-sub-l">Gear</span><span class="bk-sub-v" id="bk-gear">${S.gear}/${S.profile?.virtual_gears?.count || 24}</span></div>` : ''}
    </div>

    <div class="card bk-strip">
      <div id="bk-step-now">—</div>
      <div id="bk-step-next" class="act-meta"></div>
    </div>
    <div id="bk-prompt" class="bk-prompt" hidden></div>

    <div class="bk-controls">
      <button class="btn btn-ghost bk-ctl" id="bk-back" aria-label="Previous interval">${bikeIcons.prev}</button>
      <button class="btn btn-primary bk-ctl bk-ctl-big" id="bk-pause" aria-label="Pause or resume">${bikeIcons.pause}<span id="bk-pause-l">Pause</span></button>
      <button class="btn btn-ghost bk-ctl" id="bk-skip" aria-label="Skip interval">${bikeIcons.next}</button>
      <span class="bk-ctl-gap"></span>
      <button class="btn btn-ghost bk-ctl" id="bk-bias-dn" aria-label="Intensity down 1 percent">−</button>
      <span class="bk-bias" id="bk-bias">Bias 100%</span>
      <button class="btn btn-ghost bk-ctl" id="bk-bias-up" aria-label="Intensity up 1 percent">+</button>
      <span class="bk-ctl-gap"></span>
      <button class="btn btn-ghost bk-ctl" id="bk-erg" aria-pressed="${p.erg}">ERG ${p.erg ? 'on' : 'off'}</button>
      ${free ? `<button class="btn btn-ghost bk-ctl" id="bk-w-dn" aria-label="Target down 10 watts">−10W</button>
      <button class="btn btn-ghost bk-ctl" id="bk-w-up" aria-label="Target up 10 watts">+10W</button>` : ''}
      <span class="bk-ctl-gap"></span>
      <button class="btn btn-danger bk-ctl" id="bk-end">${S.mode === 'ramp' ? 'End test' : 'End ride'}</button>
    </div>
  </div>`;

  S.ui = {
    dim: document.getElementById('bk-dim'),
    trace: document.getElementById('bk-trace'),
    cursor: document.getElementById('bk-cursor'),
    pwr: document.getElementById('bk-pwr'),
    tgt: document.getElementById('bk-tgt'),
    int: document.getElementById('bk-int'),
    time: document.getElementById('bk-time'),
    cad: document.getElementById('bk-cad'),
    hr: document.getElementById('bk-hr'),
    np: document.getElementById('bk-np'),
    if: document.getElementById('bk-if'),
    tss: document.getElementById('bk-tss'),
    kj: document.getElementById('bk-kj'),
    wbalFill: document.getElementById('bk-wbal-fill'),
    wbalV: document.getElementById('bk-wbal-v'),
    gear: document.getElementById('bk-gear'),
    stepNow: document.getElementById('bk-step-now'),
    stepNext: document.getElementById('bk-step-next'),
    prompt: document.getElementById('bk-prompt'),
    pauseL: document.getElementById('bk-pause-l'),
    bias: document.getElementById('bk-bias'),
    erg: document.getElementById('bk-erg'),
    graphTotal: total,
    graphMaxW: maxW,
  };

  document.getElementById('bk-pause').addEventListener('click', () => p.togglePause());
  document.getElementById('bk-skip').addEventListener('click', () => p.skip());
  document.getElementById('bk-back').addEventListener('click', () => p.back());
  document.getElementById('bk-bias-dn').addEventListener('click', () => p.addBias(-1));
  document.getElementById('bk-bias-up').addEventListener('click', () => p.addBias(1));
  document.getElementById('bk-erg').addEventListener('click', async () => {
    await p.setErg(!p.erg);
    S.ui.erg.setAttribute('aria-pressed', String(p.erg));
    S.ui.erg.textContent = `ERG ${p.erg ? 'on' : 'off'}`;
    if (S.mode === 'freeride') applyGear(); // ERG off in free ride → sim grade from gear
  });
  document.getElementById('bk-w-dn')?.addEventListener('click', () => p.addWatts(-10));
  document.getElementById('bk-w-up')?.addEventListener('click', () => p.addWatts(10));
  document.getElementById('bk-end').addEventListener('click', endRide);

  S.onTick = snap => updatePlayer(snap);
  S.onPrompt = ({ message }) => showPrompt(message);
  S.onDone = () => { H.toast('ok', 'Workout complete', 'Nice ride.'); endRide(); };
  p.on('tick', S.onTick);
  p.on('prompt', S.onPrompt);
  p.on('done', S.onDone);

  // Zwift Ride buttons: shift → virtual gears (free ride), A pause, B skip, Y/Z bias.
  if (S.ride?.connected) {
    S.rideBtnHandler = ({ name, pressed }) => {
      if (!pressed || S.screen !== 'player' || !S.player) return;
      if (name === 'a') S.player.togglePause();
      else if (name === 'b') S.player.skip();
      else if (name === 'y') S.player.addBias(-1);
      else if (name === 'z') S.player.addBias(1);
      else if (name.startsWith('shiftUp')) shiftGear(1);
      else if (name.startsWith('shiftDown')) shiftGear(-1);
    };
    S.ride.on('button', S.rideBtnHandler);
  }

  // Keyboard: space pause, ↑/↓ intensity, ←/→ back/skip.
  S.keyHandler = e => {
    if (S.screen !== 'player' || !S.player || !S.page.isConnected) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) return;
    const acts = {
      ' ': () => S.player.togglePause(),
      ArrowUp: () => S.player.addBias(1),
      ArrowDown: () => S.player.addBias(-1),
      ArrowRight: () => S.player.skip(),
      ArrowLeft: () => S.player.back(),
    };
    if (acts[e.key]) { e.preventDefault(); acts[e.key](); }
  };
  document.addEventListener('keydown', S.keyHandler);

  acquireWakeLock();
  S.visHandler = () => { if (document.visibilityState === 'visible' && S.screen === 'player') acquireWakeLock(); };
  document.addEventListener('visibilitychange', S.visHandler);

  updatePlayer(p.snapshot());
}

function detachPlayerUI() {
  if (S.player) {
    if (S.onTick) S.player.off('tick', S.onTick);
    if (S.onPrompt) S.player.off('prompt', S.onPrompt);
    if (S.onDone) S.player.off('done', S.onDone);
  }
  if (S.ride && S.rideBtnHandler) { S.ride.off('button', S.rideBtnHandler); S.rideBtnHandler = null; }
  if (S.keyHandler) { document.removeEventListener('keydown', S.keyHandler); S.keyHandler = null; }
  if (S.visHandler) { document.removeEventListener('visibilitychange', S.visHandler); S.visHandler = null; }
  S.wakeLock?.release?.().catch(() => {});
  S.wakeLock = null;
}

async function acquireWakeLock() {
  try { S.wakeLock = await navigator.wakeLock?.request('screen'); } catch { /* not fatal */ }
}

function shiftGear(delta) {
  const gears = S.profile?.virtual_gears || { count: 24 };
  S.gear = Math.min(gears.count || 24, Math.max(1, S.gear + delta));
  if (S.ui.gear) S.ui.gear.textContent = `${S.gear}/${gears.count || 24}`;
  applyGear();
}

function applyGear() {
  if (S.mode !== 'freeride' || !S.player || S.player.erg) return;
  // ponytail: flat-course gearing as pseudo-grade — 0.4%/gear around the middle
  // ring; replace with ratio-based wheel-speed model if it ever feels wrong.
  const grade = (S.gear - 12) * 0.4;
  S.trainer.setSimGrade(grade).catch(() => {});
}

function stepLabel(step) {
  if (!step) return '—';
  const kind = { warmup: 'Warm-up', cooldown: 'Cool-down', ramp: 'Ramp', steady: 'Steady', on: 'Work', off: 'Recover', freeride: 'Free ride', maxeffort: 'Max effort' }[step.kind] || step.kind;
  if (step.powerStartW == null) return `${kind} · ${fmtDur(step.duration)}`;
  const pw = step.powerStartW === step.powerEndW ? `${step.powerStartW} W` : `${step.powerStartW}→${step.powerEndW} W`;
  return `${kind} · ${fmtDur(step.duration)} @ ${pw}`;
}

function updatePlayer(snap) {
  const u = S.ui;
  if (!u.pwr || !u.pwr.isConnected) return;
  const zone = snap.zone;
  u.pwr.innerHTML = `${Math.round(snap.power3s)}<span class="bk-unit">W</span>`;
  u.pwr.style.color = zone ? zone.color : 'var(--text)';
  u.tgt.textContent = snap.target != null ? `${snap.target} W` : '—';
  u.int.textContent = snap.stepRemaining != null ? fmtDur(snap.stepRemaining) : '—';
  u.time.textContent = snap.remaining != null
    ? `${fmtDur(snap.t)} · ${fmtDur(snap.remaining)}` : fmtDur(snap.t);
  u.cad.textContent = snap.cadence != null
    ? `${Math.round(snap.cadence)}${snap.step?.cadence ? ` / ${snap.step.cadence}` : ''}` : '—';
  u.hr.textContent = snap.hr != null ? String(snap.hr) : '—';
  u.np.textContent = String(Math.round(snap.np));
  u.if.textContent = snap.if.toFixed(2);
  u.tss.textContent = String(Math.round(snap.tss));
  u.kj.textContent = String(Math.round(snap.kj));
  u.wbalFill.style.width = `${Math.round(snap.wbalPct * 100)}%`;
  u.wbalV.textContent = `${Math.round(snap.wbalPct * 100)}%`;
  u.stepNow.textContent = stepLabel(snap.step);
  u.stepNext.textContent = snap.nextStep ? `Next: ${stepLabel(snap.nextStep)}` : (snap.step ? 'Last interval' : '');
  u.pauseL.textContent = snap.paused ? 'Resume' : 'Pause';
  u.bias.textContent = `Bias ${snap.bias}%`;
  if (S.mode === 'freeride' && snap.erg) u.tgt.textContent = `${snap.ergWatts} W`;

  // graph: cursor + dim + actual trace (3s-smoothed)
  if (Number.isFinite(u.graphTotal) && u.graphTotal > 0) {
    const x = Math.min(1000, (snap.t / u.graphTotal) * 1000);
    u.cursor.setAttribute('x1', x);
    u.cursor.setAttribute('x2', x);
    u.dim.setAttribute('width', x);
    if (!snap.paused) {
      const y = 180 - Math.min(snap.power3s / u.graphMaxW, 1) * 178;
      S.trace.push(`${x.toFixed(1)},${y.toFixed(1)}`);
      u.trace.setAttribute('points', S.trace.join(' '));
    }
  }
}

let promptTimer = null;
function showPrompt(message) {
  const el = S.ui.prompt;
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
  clearTimeout(promptTimer);
  promptTimer = setTimeout(() => { el.hidden = true; }, 10000);
}

// ═══════════ POST-RIDE ═══════════

function renderPost() {
  const r = S.result;
  if (!r) { S.screen = 'home'; return renderHome(); }
  H.setTopbar('Bike', 'Ride complete');
  const s = r.data.summary;
  const laps = r.data.laps || [];
  const recs = r.data.records || [];
  const lapRows = laps.map((lap, i) => {
    const inLap = recs.filter(rec => rec.tMs >= lap.startMs && (i === laps.length - 1 ? rec.tMs <= lap.endMs : rec.tMs < lap.endMs));
    const avgOf = key => {
      const xs = inLap.map(x => x[key]).filter(v => v != null);
      return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
    };
    const ap = avgOf('power'), ah = avgOf('hr'), ac = avgOf('cadence');
    return `<tr><td>${i + 1}</td><td>${fmtDur((lap.endMs - lap.startMs) / 1000)}</td>
      <td>${ap != null ? Math.round(ap) + ' W' : '—'}</td>
      <td>${ah != null ? Math.round(ah) : '—'}</td>
      <td>${ac != null ? Math.round(ac) : '—'}</td></tr>`;
  }).join('');
  const rampFtp = r.mode === 'ramp' && r.best60 ? rampTestFtp(r.best60) : null;
  const icuKey = (sessionStorage.getItem(INTERVALS_KEY) || '').trim();
  const stravaTok = (sessionStorage.getItem(STRAVA_KEY) || '').trim();
  const stat = (label, v, unit = '') => `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${v}<span class="unit">${unit}</span></div></div>`;

  S.page.innerHTML = `
  ${rampFtp ? `
  <div class="card" style="margin-bottom:18px;border-color:rgba(167,139,250,.4)">
    <div class="card-h"><div class="card-title"><span class="ico" style="color:var(--violet)">${bikeIcons.gauge}</span>Ramp test result</div></div>
    <div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap">
      <div class="stat-value" style="font-size:2.6rem">${rampFtp}<span class="unit">W FTP</span></div>
      <div class="act-meta" style="flex:1">Best 1-minute power ${Math.round(r.best60)} W × 0.75. Applying updates your profile and rescales every workout.</div>
      <button class="btn btn-primary" id="bk-ftp-apply">Apply FTP ${rampFtp}</button>
      <button class="btn btn-outline" id="bk-ftp-dismiss">Dismiss</button>
    </div>
  </div>` : ''}
  <div class="dash-grid">
    <div class="card span-7">
      <div class="card-h"><div class="card-title"><span class="ico">${bikeIcons.bike}</span>${H.escHtml(r.workoutName)}${r.recovered ? ' (recovered)' : ''}</div></div>
      <div class="grid stat-row" style="margin-bottom:18px">
        ${stat('Duration', fmtDur(s.durationSec))}
        ${stat('Avg power', s.avgPower != null ? Math.round(s.avgPower) : '—', ' W')}
        ${stat('Max power', s.maxPower != null ? Math.round(s.maxPower) : '—', ' W')}
        ${stat('NP', s.np != null ? Math.round(s.np) : '—', ' W')}
        ${stat('IF', s.if_ != null ? s.if_.toFixed(2) : '—')}
        ${stat('TSS', s.tss != null ? Math.round(s.tss) : '—')}
        ${stat('Energy', s.kj != null ? Math.round(s.kj) : '—', ' kJ')}
        ${stat('Avg HR', s.avgHr != null ? Math.round(s.avgHr) : '—', ' bpm')}
        ${stat('Avg cadence', s.avgCadence != null ? Math.round(s.avgCadence) : '—', ' rpm')}
      </div>
      ${laps.length > 1 ? `<div class="bk-laps-wrap"><table class="bk-laps">
        <thead><tr><th>Lap</th><th>Time</th><th>Avg pwr</th><th>Avg HR</th><th>Avg cad</th></tr></thead>
        <tbody>${lapRows}</tbody></table></div>` : ''}
    </div>
    <div class="card span-5">
      <div class="card-h"><div class="card-title"><span class="ico">${bikeIcons.save}</span>Save &amp; share</div></div>
      <div class="field"><label for="bk-notes">Notes</label><textarea id="bk-notes" rows="3" placeholder="How did it feel?"></textarea></div>
      <div class="bk-post-btns">
        <button class="btn btn-ghost" id="bk-fit">${bikeIcons.download}Download .FIT</button>
        <button class="btn btn-ghost" id="bk-icu-up" ${icuKey ? '' : 'disabled'}>Upload to intervals.icu</button>
        <button class="btn btn-ghost" id="bk-strava-up" ${stravaTok ? '' : 'disabled'}>Upload to Strava</button>
        <button class="btn btn-primary" id="bk-save">Save to PaceForge</button>
        <button class="btn btn-outline" id="bk-done">Done</button>
      </div>
      ${!icuKey || !stravaTok ? `<div class="hint" style="margin-top:10px">Add ${!icuKey ? 'an intervals.icu key' : ''}${!icuKey && !stravaTok ? ' / ' : ''}${!stravaTok ? 'a Strava token' : ''} under Integrations on the Bike home to enable uploads.</div>` : ''}
    </div>
  </div>`;

  const fitBytes = () => encodeRideFit({
    startTimeMs: r.startTimeMs, records: recs, laps, ftp: r.ftpUsed,
    totals: { durationSec: s.durationSec, np: s.np, kj: s.kj, distanceM: s.distanceM },
  });
  const fitName = () => {
    const d = new Date(r.startTimeMs);
    const pad = n => String(n).padStart(2, '0');
    return `paceforge-ride-${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}.fit`;
  };

  document.getElementById('bk-fit').addEventListener('click', () => {
    try {
      const blob = new Blob([fitBytes()], { type: 'application/octet-stream' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = fitName();
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) { H.toast('err', 'FIT export failed', H.escHtml(e.message)); }
  });

  document.getElementById('bk-icu-up').addEventListener('click', function () {
    H.withBusy(this, 'Uploading…', async () => {
      await uploadIntervalsIcu(fitBytes(), { apiKey: icuKey, name: S.result.workoutName });
      H.toast('ok', 'Uploaded', 'Ride sent to intervals.icu.');
    });
  });
  document.getElementById('bk-strava-up').addEventListener('click', function () {
    H.withBusy(this, 'Uploading…', async () => {
      await uploadStrava(fitBytes(), { accessToken: stravaTok, name: S.result.workoutName });
      H.toast('ok', 'Uploaded', 'Ride sent to Strava.');
    });
  });

  document.getElementById('bk-save').addEventListener('click', function () {
    const entry = {
      date: new Date(r.startTimeMs).toISOString().slice(0, 19),
      workout: r.workoutName,
      duration_sec: Math.round(s.durationSec),
      avg_power: s.avgPower, np: s.np, if: s.if_, tss: s.tss, kj: s.kj,
      avg_hr: s.avgHr, avg_cadence: s.avgCadence, ftp: r.ftpUsed,
      notes: document.getElementById('bk-notes').value.trim() || null,
    };
    H.withBusy(this, 'Saving…', async () => {
      const res = await fetch(`${H.API}/repos/${H.REPO}/actions/workflows/save-ride.yml/dispatches`, {
        method: 'POST', headers: H.JSON_HDR,
        body: JSON.stringify({ inputs: { data: JSON.stringify(entry) } }),
      });
      if (res.status !== 204) throw new Error(`Runner error ${res.status}`);
      const pending = ls(PENDING_KEY, []);
      pending.unshift(entry);
      lsSet(PENDING_KEY, pending.slice(0, 10));
      H.toast('ok', 'Ride saved', 'Logged to PaceForge — appears in history after the next site build.');
    });
  });

  document.getElementById('bk-done').addEventListener('click', () => { S.result = null; S.screen = 'home'; renderHome(); });
  document.getElementById('bk-ftp-apply')?.addEventListener('click', function () {
    saveProfilePatch({ ftp: rampFtp, source: 'ramp_test' }, this);
  });
  document.getElementById('bk-ftp-dismiss')?.addEventListener('click', e => e.target.closest('.card').remove());
}

// ── Icons (24px stroke, matching the host icon voice) ──
const bikeIcons = {
  bike: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="5.5" cy="17.5" r="3.5"/><circle cx="18.5" cy="17.5" r="3.5"/><path d="M5.5 17.5 9 11h6l3.5 6.5"/><path d="m9 11-1.5-4H5"/><path d="M15 11 13.5 6H12"/></svg>`,
  bt: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m7 7 10 10-5 5V2l5 5L7 17"/></svg>`,
  gauge: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15 8.5 9.5"/><path d="M20.5 15a8.5 8.5 0 1 0-17 0"/><path d="M4 15h2M18 15h2"/></svg>`,
  history: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 3"/></svg>`,
  link: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg>`,
  pause: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 5v14M15 5v14"/></svg>`,
  prev: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m17 18-8-6 8-6"/><path d="M7 6v12"/></svg>`,
  next: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m7 6 8 6-8 6"/><path d="M17 6v12"/></svg>`,
  save: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>`,
  download: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M5 21h14"/></svg>`,
  alert: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>`,
};
