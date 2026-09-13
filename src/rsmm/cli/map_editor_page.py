# ruff: noqa: E501  (the string below is HTML/JS, not Python)
"""The map editor's single page: HTML, CSS and JS, no build step, no assets.

Kept as a Python module rather than a data file so the frozen CLI bundles it
through `--collect-submodules=rsmm.cli` like every other command, instead of
needing a new `--add-data` line in two build scripts that must stay in sync.

The 3D view is plain WebGL2 with no library, so the page works offline and the
server's CSP can stay `'self'`-only. The terrain it draws is fetched from
`/api/terrain`, which reads the user's own install (or local `data/uncooked`
mirror) at request time; nothing game-derived is embedded here.

`__RSMM_TOKEN__` is replaced per launch with the token every write request must
echo back; see `cmd_map_editor`.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ravenswatch Map Editor</title>
<style>
:root {
  --bg: #f4f3ef; --panel: #ffffff; --ink: #1d1d1f; --muted: #66666c; --line: #deddd8;
  --accent: #7a3cff; --ok: #1f9d55; --warn: #c77700; --bad: #c0392b; --idle: #a9a8a3;
  --changed: #fff2c2; --gw: #8b8b8b; --chip: #efeee9;
  --g0: #4f86c6; --g1: #3aa39a; --g2: #d9822b; --g3: #b54a8c; --g4: #8a6fd1; --g5: #7c9a2f; --g6: #c9544d; --g7: #2f8fb0;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131315; --panel: #1c1c1f; --ink: #ececf0; --muted: #9d9da5; --line: #313136;
    --accent: #a987ff; --ok: #3ccb7f; --warn: #f0a63c; --bad: #ff6b5e; --idle: #5a5a60;
    --changed: #4a3d12; --gw: #77777d; --chip: #26262a;
    --g0: #6fa4e0; --g1: #52c2b8; --g2: #f09a45; --g3: #d06aa8; --g4: #a891ea; --g5: #9cbd48; --g6: #e8736b; --g7: #4fb0d2;
  }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--ink); display: flex; flex-direction: column; height: 100vh;
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
header { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center;
  padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }
header h1 { font-size: 15px; margin: 0 4px 0 0; font-weight: 650; }
label.inline { display: flex; gap: 6px; align-items: center; color: var(--muted); }
select { max-width: 260px; }
select, input[type=text], input[type=number], input[type=search] {
  font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 6px; }
input[type=number] { width: 70px; }
button { font: inherit; border: 1px solid var(--line); background: var(--bg); color: var(--ink);
  border-radius: 6px; padding: 5px 12px; cursor: pointer; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.small { padding: 1px 7px; font-size: 12px; }
button.undo { border: none; background: none; color: var(--warn); padding: 0 4px; font-size: 15px; line-height: 1; }
button:disabled { opacity: .5; cursor: default; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 7px; overflow: hidden; }
.seg button { border: none; border-radius: 0; padding: 4px 10px; }
.seg button[aria-pressed=true] { background: var(--accent); color: #fff; }
#status { margin-left: auto; color: var(--muted); max-width: 52ch; }
#status.bad { color: var(--bad); } #status.ok { color: var(--ok); }
main { display: grid; grid-template-columns: minmax(0, 1fr) 540px; gap: 12px;
  padding: 12px 16px; flex: 1; min-height: 0; }
@media (max-width: 1100px) { body { height: auto; } main { grid-template-columns: 1fr; } #viewport { height: 70vh; } }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  display: flex; flex-direction: column; min-height: 0; }
.card > .head { padding: 8px 12px; border-bottom: 1px solid var(--line);
  display: flex; gap: 8px 12px; align-items: center; flex-wrap: wrap; }
#viewport { position: relative; flex: 1; min-height: 380px; overflow: hidden; border-radius: 0 0 10px 10px; }
#map, #gl { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
#gl { cursor: grab; touch-action: none; } #gl.dragging { cursor: grabbing; }
#tip { position: absolute; pointer-events: none; background: var(--panel); color: var(--ink);
  border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; font-size: 12px;
  box-shadow: 0 2px 8px #0003; white-space: nowrap; z-index: 3; }
#hint { position: absolute; right: 10px; bottom: 10px; font-size: 12px; color: var(--muted);
  background: color-mix(in srgb, var(--panel) 85%, transparent); padding: 3px 8px; border-radius: 6px; z-index: 2; }
#legend { position: absolute; right: 10px; top: 10px; z-index: 2; font-size: 12px; max-width: 46%;
  background: color-mix(in srgb, var(--panel) 90%, transparent); border: 1px solid var(--line);
  padding: 6px 9px; border-radius: 8px; display: flex; flex-direction: column; gap: 2px; }
#legend b { font-weight: 600; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
#load { position: absolute; left: 50%; top: 12px; transform: translateX(-50%); z-index: 2; font-size: 12px;
  background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 3px 12px; }
#nogl { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: var(--muted); padding: 24px; text-align: center; }
.tabs { display: flex; gap: 2px; flex-wrap: wrap; }
.tabs button { border: none; background: none; padding: 6px 10px; border-radius: 6px; }
.tabs button[aria-selected=true] { background: var(--bg); color: var(--accent); font-weight: 600; }
.tabs .num { display: inline-block; min-width: 18px; height: 18px; line-height: 18px; border-radius: 9px;
  background: var(--chip); color: var(--muted); font-size: 11px; text-align: center; margin-right: 5px; }
.tabs button[aria-selected=true] .num { background: var(--accent); color: #fff; }
.body { overflow: auto; padding: 10px 12px; flex: 1; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 4px 6px; vertical-align: middle; }
th { color: var(--muted); font-weight: 500; font-size: 12px; position: sticky; top: 0; background: var(--panel); z-index: 1; }
tbody.kind td { border-bottom: none; }
tbody.kind tr:last-child td { border-bottom: 1px solid var(--line); padding-bottom: 7px; }
tbody.kind.sel td { background: color-mix(in srgb, var(--accent) 11%, transparent); }
td.changed, label.changed { background: var(--changed); border-radius: 4px; }
.kname { cursor: pointer; font-weight: 560; }
.kname:hover { color: var(--accent); }
.badge { display: inline-block; padding: 0 7px; border-radius: 9px; background: var(--chip); font-size: 12px; cursor: pointer; }
.badge.warn { color: #fff; background: var(--warn); }
.fp { display: flex; gap: 4px 6px; flex-wrap: wrap; font-size: 12px; color: var(--muted); align-items: center; }
.chipbox { display: inline-flex; gap: 3px; align-items: center; padding: 0 6px 0 3px; border-radius: 9px; background: var(--chip); }
.muted { color: var(--muted); } .warn { color: var(--warn); } .okc { color: var(--ok); }
details.help { background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; margin-bottom: 10px; }
details.help summary { cursor: pointer; font-weight: 600; }
details.help ul { margin: 6px 0 2px; padding-left: 18px; } details.help li { margin: 3px 0; }
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
ul.changes { margin: 6px 0 12px; padding-left: 0; list-style: none; }
ul.changes li { display: flex; justify-content: space-between; gap: 8px; padding: 4px 0; border-bottom: 1px solid var(--line); }
.slotinfo { display: grid; grid-template-columns: auto 1fr; gap: 2px 14px; margin-bottom: 10px; }
.kgrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 3px 12px; margin: 4px 0 10px; }
.kgrid label { display: flex; gap: 5px; align-items: baseline; padding: 1px 4px; }
.form { display: grid; grid-template-columns: auto 1fr; gap: 8px 12px; align-items: center; margin: 10px 0; }
.form input { width: 100%; }
pre.cmd { background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; margin: 6px 0; white-space: pre-wrap; }
h3 { font-size: 13px; margin: 12px 0 4px; }
svg text { fill: var(--ink); font-size: 20px; paint-order: stroke; stroke: var(--panel); stroke-width: 4px; }
svg .scale { stroke: var(--ink); stroke-width: 3; }
.slot { cursor: pointer; }
.slot:hover { stroke: var(--ink); stroke-width: 3; }
</style>
</head>
<body>
<header>
  <h1>Map Editor</h1>
  <label class="inline">Chapter <select id="chapter"></select></label>
  <label class="inline" title="The game picks one of these for each run. Some spots allow different tiles per scenario.">Scenario <select id="scenario"></select></label>
  <label class="inline">Open saved mod <select id="openmod"><option value="">—</option></select></label>
  <span id="status" role="status" aria-live="polite">Loading…</span>
</header>
<main>
  <section class="card" aria-label="Map">
    <div class="head">
      <div class="seg" role="group" aria-label="View">
        <button id="v3d" aria-pressed="true">3D</button>
        <button id="v2d" aria-pressed="false">Top-down</button>
      </div>
      <button id="recenter" class="small" title="Reset the camera">Reset view</button>
      <label class="inline" title="Draw the chapter's scenery and tiles with the game's own models (read from data/uncooked)"><input type="checkbox" id="models" checked> Models</label>
      <label class="inline"><input type="checkbox" id="spots" checked> Spots</label>
      <button id="sample" class="small" title="Fill the spots with tiles from this chapter's pool, roughly the way a run would">Sample layout</button>
      <button id="clearlayout" class="small" hidden>Clear tiles</button>
      <label class="inline" title="With a tile picked, also draw the spots it is not allowed on"><input type="checkbox" id="showall" checked> Show unusable spots</label>
      <strong id="maptitle" class="muted" style="margin-left:auto">—</strong>
    </div>
    <div id="viewport">
      <canvas id="gl" aria-label="3D view of the chapter terrain and tile spots"></canvas>
      <svg id="map" role="img" aria-label="Tile spots plotted from above" hidden></svg>
      <div id="nogl" hidden></div>
      <div id="legend"></div>
      <div id="hint"></div>
      <div id="load" hidden></div>
      <div id="tip" hidden></div>
    </div>
  </section>
  <section class="card" aria-label="Recipe">
    <div class="head tabs" role="tablist">
      <button role="tab" aria-selected="true" data-tab="kinds"><span class="num">1</span>Tiles</button>
      <button role="tab" aria-selected="false" data-tab="slot"><span class="num">2</span>Spot</button>
      <button role="tab" aria-selected="false" data-tab="quotas"><span class="num">3</span>Limits</button>
      <button role="tab" aria-selected="false" data-tab="changes"><span class="num">4</span>Review &amp; save <span id="nchanges"></span></button>
    </div>
    <div class="body" id="panel"></div>
  </section>
</main>
<script type="module">
// three.js is served by the editor itself (vendored, MIT; see map_editor_static).
let THREE = null;
try { THREE = await import("/static/three.module.min.js"); } catch (err) { console.error(err); }
const TOKEN = "__RSMM_TOKEN__";
const $ = (id) => document.getElementById(id);
const S = { chapters: [], chapter: null, orig: null, work: null, kind: null, slot: null, tab: "kinds",
  scen: 0, view: "3d", terrain: null, filter: "", showAll: true, lastSave: null,
  models: true, showSpots: true, layout: {}, pool: [], seed: 1, sceneInfo: null, modelsError: null };
const GROUP_COLORS = ["--g0", "--g1", "--g2", "--g3", "--g4", "--g5", "--g6", "--g7"];
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };

function status(msg, cls) { const el = $("status"); el.textContent = msg; el.className = cls || ""; }
function clone(o) { return JSON.parse(JSON.stringify(o)); }
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
const nice = (n) => String(n).replace(/_/g, " ");
const sizeLabel = (g) => String(g).replace("x", "×") + " m";

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-RSMM-Token": TOKEN},
    body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({ error: "bad response (" + r.status + ")" }));
  if (!r.ok || data.error) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

// ---- edits: the diff between the shipped recipe and the working copy ------
function edits() {
  const e = { kinds: {}, quotas: {}, slots: {} };
  S.work.kinds.forEach((k, i) => {
    const o = S.orig.kinds[i], d = {};
    if (k.count !== o.count) d.count = k.count;
    if (Math.abs(k.min_distance - o.min_distance) > 1e-4) d.min_distance = k.min_distance;
    const fp = {};
    for (const g in k.footprints) if (k.footprints[g] !== o.footprints[g]) fp[g] = k.footprints[g];
    if (Object.keys(fp).length) d.footprints = fp;
    if (Object.keys(d).length) e.kinds[k.name] = d;
  });
  S.work.quotas.forEach((q, i) => { if (q.limit !== S.orig.quotas[i].limit) e.quotas[q.key] = q.limit; });
  S.work.slots.forEach((s, i) => {
    const o = S.orig.slots[i], allow = {};
    for (const k in s.allow) if (s.allow[k] !== o.allow[k]) allow[k] = s.allow[k];
    if (Object.keys(allow).length) e.slots[String(s.id)] = { pos: o.pos, allow };
  });
  for (const k of ["kinds", "quotas", "slots"]) if (!Object.keys(e[k]).length) delete e[k];
  return e;
}
// Plain-language change list; each entry knows how to undo itself.
function changeList() {
  const out = [];
  S.work.kinds.forEach((k, i) => {
    const o = S.orig.kinds[i];
    if (k.count !== o.count) out.push({ text: `${nice(k.name)}: ${o.count} → ${k.count} per run`, undo: () => { k.count = o.count; } });
    if (Math.abs(k.min_distance - o.min_distance) > 1e-4) out.push({ text: `${nice(k.name)}: spacing ${o.min_distance} m → ${k.min_distance} m`, undo: () => { k.min_distance = o.min_distance; } });
    for (const g in k.footprints) if (k.footprints[g] !== o.footprints[g]) {
      out.push({ text: `${nice(k.name)}: ${k.footprints[g] ? "now fits" : "no longer fits"} ${sizeLabel(g)} spots`, undo: () => { k.footprints[g] = o.footprints[g]; } });
    }
  });
  S.work.quotas.forEach((q, i) => {
    const o = S.orig.quotas[i];
    if (q.limit !== o.limit) out.push({ text: `Limit ${nice(q.flags.join(" + "))}: at most ${o.limit} → ${q.limit}`, undo: () => { q.limit = o.limit; } });
  });
  S.work.slots.forEach((s, i) => {
    const o = S.orig.slots[i];
    for (const k in s.allow) if (s.allow[k] !== o.allow[k]) {
      out.push({ text: `Spot ${s.id}: ${nice(k)} ${s.allow[k] ? "allowed" : "not allowed"}`, undo: () => { s.allow[k] = o.allow[k]; } });
    }
  });
  return out;
}

// ---- eligibility: where a kind could possibly stand -------------------------
// Per scenario the compatibility table may override the slot's mask: 1 forces
// the kind allowed, 0 forbids it, and anything not listed defers to the mask.
function allowedHere(slot, kind) {
  const ov = (slot.overrides[S.scen] || {})[kind.name];
  if (ov === 1) return true;
  if (ov === 0) return false;
  return !!slot.allow[kind.name];
}
function eligible(slot, kind) {
  if (slot.whole_map || !allowedHere(slot, kind)) return "no";
  return kind.footprints[slot.group] ? "yes" : "blocked";
}
function eligibleCount(kind) { return S.work.slots.filter(s => eligible(s, kind) === "yes").length; }
function slotChanged(s) {
  const o = S.orig.slots.find(x => x.id === s.id);
  return Object.keys(s.allow).some(k => s.allow[k] !== o.allow[k]);
}
function fitsNow(s) { return S.work.kinds.filter(k => eligible(s, k) === "yes"); }

// ---- colours ----------------------------------------------------------------
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function hexRgb(h) {
  h = h.replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join("");
  const v = parseInt(h, 16); return [(v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255];
}
function groupVar(name) {
  const i = S.work.groups.findIndex(g => g.name === name);
  return i < 0 ? "--gw" : GROUP_COLORS[i % GROUP_COLORS.length];
}
// What a spot looks like right now: [css var, opacity, emphasis 0..1].
function slotLook(s) {
  const kind = S.kind != null ? S.work.kinds[S.kind] : null;
  if (!kind) return [groupVar(s.group), 0.9, 0.6];
  const e = eligible(s, kind);
  return e === "yes" ? ["--ok", 1, 1] : e === "blocked" ? ["--warn", 0.75, 0.55] : ["--idle", 0.35, 0.15];
}
function visibleSlot(s) {
  if (s.whole_map) return false;
  if (S.showAll || S.kind == null) return true;
  return eligible(s, S.work.kinds[S.kind]) !== "no";
}

// ---- terrain ----------------------------------------------------------------
function decodeTerrain(t) {
  const n = t.grid, b64 = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const u16 = (o) => { const raw = b64(o.u16), v = new DataView(raw.buffer), out = new Float32Array(n * n);
    for (let i = 0; i < n * n; i++) out[i] = o.min + v.getUint16(2 * i, true) / 65535 * (o.max - o.min);
    return out; };
  const u8 = (s) => { if (!s) return null; const raw = b64(s), out = new Float32Array(n * n); for (let i = 0; i < n * n; i++) out[i] = raw[i] / 255; return out; };
  return { n, min: t.box_min, max: t.box_max, h: u16(t.height), path: u8(t.path), block: u8(t.block),
           water: t.water ? u16(t.water) : null, hmin: t.height.min, hmax: t.height.max };
}
// Ground colour of one cell: a moss-to-stone height ramp, sandy design paths,
// darker blocked ground. Shared by the 3D mesh and the top-down image.
function groundColor(T, i) {
  const t = Math.max(0, Math.min(1, (T.h[i] - T.hmin) / ((T.hmax - T.hmin) || 1)));
  const lo = [0.29, 0.36, 0.25], mid = [0.50, 0.56, 0.36], hi = [0.78, 0.76, 0.62];
  const a = t < 0.5 ? lo : mid, b = t < 0.5 ? mid : hi, f = t < 0.5 ? t * 2 : (t - 0.5) * 2;
  let c = [0, 1, 2].map(k => a[k] + (b[k] - a[k]) * f);
  if (T.block && T.block[i] > 0.05) { const w = Math.min(1, T.block[i]) * 0.6; c = c.map((v, k) => v + ([0.36, 0.30, 0.32][k] - v) * w); }
  if (T.path && T.path[i] > 0.05) { const w = Math.min(1, T.path[i]) * 0.85; c = c.map((v, k) => v + ([0.85, 0.72, 0.47][k] - v) * w); }
  return c;
}
function wet(T, i) { return T.water && T.water[i] > T.h[i] + 0.05; }
function terrainImage(T) {
  const n = T.n, cv = document.createElement("canvas"); cv.width = n; cv.height = n;
  const ctx = cv.getContext("2d"), img = ctx.createImageData(n, n);
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) {
    const i = r * n + c, o = ((n - 1 - r) * n + c) * 4;   // +z is up on screen
    const dx = T.h[r * n + Math.min(n - 1, c + 1)] - T.h[r * n + Math.max(0, c - 1)];
    const dz = T.h[Math.min(n - 1, r + 1) * n + c] - T.h[Math.max(0, r - 1) * n + c];
    const shade = Math.max(0.55, Math.min(1.25, 1 - (dx * 0.5 - dz * 0.35) * 0.12));
    let col = groundColor(T, i).map(v => v * shade);
    if (wet(T, i)) col = col.map((v, k) => v * 0.35 + [0.25, 0.5, 0.72][k] * 0.65);
    img.data[o] = col[0] * 255; img.data[o + 1] = col[1] * 255; img.data[o + 2] = col[2] * 255; img.data[o + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return new Promise(res => cv.toBlob(b => res(URL.createObjectURL(b))));
}

// ---- top-down view (SVG) ----------------------------------------------------
function renderMap() {
  const svg = $("map");
  const slots = S.work.slots.filter(s => !s.whole_map);
  const xs = slots.map(s => s.pos[0]), zs = slots.map(s => s.pos[2]);
  const minX = Math.min(...xs) - 40, maxX = Math.max(...xs) + 40, minZ = Math.min(...zs) - 40, maxZ = Math.max(...zs) + 40;
  const pad = 10, span = Math.max(maxX - minX, maxZ - minZ) || 1;
  const W = 1000, H = 1000, sc = (W - 2 * pad) / span;
  const px = x => pad + (x - minX) * sc, pz = z => H - pad - (z - minZ) * sc;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const parts = [];
  const T = S.terrain;
  if (T && T.imageUrl) {
    const x0 = px(T.min[0]), x1 = px(T.max[0]), y0 = pz(T.max[2]), y1 = pz(T.min[2]);
    parts.push(`<image href="${T.imageUrl}" x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" preserveAspectRatio="none"/>`);
  }
  const bar = 50 * sc;
  parts.push(`<line class="scale" x1="${pad + 12}" y1="${H - 22}" x2="${pad + 12 + bar}" y2="${H - 22}"/>`);
  parts.push(`<text x="${pad + 20 + bar}" y="${H - 15}">50 m</text>`);
  for (const s of slots) {
    if (!visibleSlot(s)) continue;
    const [v, op] = slotLook(s);
    const half = Math.max(parseFloat(s.group) * sc / 2, 5);
    const sel = S.slot === s.id, ch = slotChanged(s);
    const stroke = sel ? `stroke="var(--ink)" stroke-width="5"` : ch ? `stroke="var(--warn)" stroke-width="4"` : `stroke="#0008" stroke-width="1.5"`;
    parts.push(`<rect class="slot" data-id="${s.id}" x="${px(s.pos[0]) - half}" y="${pz(s.pos[2]) - half}" width="${2 * half}" height="${2 * half}" rx="3" fill="var(${v})" fill-opacity="${op}" ${stroke}></rect>`);
  }
  svg.innerHTML = parts.join("");
  svg.querySelectorAll(".slot").forEach(el => {
    el.addEventListener("click", () => pickSlot(Number(el.dataset.id)));
    el.addEventListener("mousemove", (ev) => showTip(ev, S.work.slots.find(s => s.id === Number(el.dataset.id))));
    el.addEventListener("mouseleave", () => { $("tip").hidden = true; });
  });
}

// ---- 3D view (three.js, vendored; see /static) ------------------------------
// Everything in the world lives under one group mirrored in Z: the engine is
// left-handed (Y up, +Z away), WebGL is right-handed, and mirroring once keeps
// every engine position, rotation and mesh usable as-is. three.js flips the
// face winding for mirrored objects on its own.
const G = { three: null, cam: { tx: 0, ty: 0, tz: 0, yaw: 0, pitch: 0.95, dist: 640 }, dirty: true,
  terrainKey: null, pickable: [], parts: new Map(), loading: 0, loaded: 0, tileCache: new Map() };

function glInit() {
  if (!THREE) return false;
  const cv = $("gl");
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true }); } catch (e) { return false; }
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 1, 6000);
  const world = new THREE.Group(); world.scale.z = -1; scene.add(world);
  scene.add(new THREE.HemisphereLight(0xdfe8f2, 0x3d3a2c, 1.35));
  const sun = new THREE.DirectionalLight(0xfff0d8, 2.6);
  sun.position.set(-220, 380, 180); sun.castShadow = true;
  Object.assign(sun.shadow.camera, { left: -300, right: 300, top: 300, bottom: -300, near: 10, far: 1200 });
  sun.shadow.mapSize.set(4096, 4096); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.6;
  scene.add(sun); scene.add(sun.target);
  const groups = {};
  for (const k of ["terrain", "scenery", "tiles", "markers"]) { groups[k] = new THREE.Group(); world.add(groups[k]); }
  G.three = { renderer, scene, camera, world, groups, sun };
  bindCamera(cv);
  new ResizeObserver(() => { G.dirty = true; }).observe(cv);
  requestAnimationFrame(frame);
  return true;
}
const srgb = (c) => c.map(v => Math.pow(Math.max(0, v), 2.2));   // vertex colours are linear
function clearGroup(g) {
  for (const o of [...g.children]) {
    g.remove(o);
    if (o.geometry && !o.userData.shared) o.geometry.dispose();
    if (o.material && !o.userData.shared) o.material.dispose();
    if (o.dispose && o.isInstancedMesh) o.dispose();
  }
}

function buildTerrain() {
  const T3 = G.three, T = S.terrain; if (!T3 || !T) return;
  const key = S.chapter.key + "|" + T.n; if (G.terrainKey === key) return;
  G.terrainKey = key; clearGroup(T3.groups.terrain);
  const n = T.n, sx = (T.max[0] - T.min[0]) / n, sz = (T.max[2] - T.min[2]) / n;
  const pos = new Float32Array(n * n * 3), col = new Float32Array(n * n * 3);
  const wpos = new Float32Array(n * n * 3), wcol = new Float32Array(n * n * 4);
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) {
    const i = r * n + c, x = T.min[0] + (c + 0.5) * sx, z = T.min[2] + (r + 0.5) * sz;
    pos.set([x, T.h[i], z], i * 3);
    col.set(srgb(groundColor(T, i)), i * 3);
    wpos.set([x, T.water ? T.water[i] : T.hmin - 1, z], i * 3);
    wcol.set([0.05, 0.2, 0.38, wet(T, i) ? 0.72 : 0], i * 4);
  }
  const idx = new Uint32Array((n - 1) * (n - 1) * 6); let k = 0;
  for (let r = 0; r < n - 1; r++) for (let c = 0; c < n - 1; c++) {
    const a = r * n + c, b = a + 1, d = a + n, e = d + 1;
    idx[k++] = a; idx[k++] = b; idx[k++] = d; idx[k++] = b; idx[k++] = e; idx[k++] = d;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1)); geo.computeVertexNormals();
  const ground = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, metalness: 0, side: THREE.DoubleSide }));
  ground.receiveShadow = true; T3.groups.terrain.add(ground);
  if (T.water) {
    const wg = new THREE.BufferGeometry();
    wg.setAttribute("position", new THREE.BufferAttribute(wpos, 3));
    wg.setAttribute("color", new THREE.BufferAttribute(wcol, 4));
    wg.setIndex(new THREE.BufferAttribute(idx, 1)); wg.computeVertexNormals();
    const water = new THREE.Mesh(wg, new THREE.MeshStandardMaterial({ vertexColors: true, transparent: true, roughness: 0.15, metalness: 0.1, depthWrite: false, side: THREE.DoubleSide }));
    water.renderOrder = 2; water.receiveShadow = true; T3.groups.terrain.add(water);
  }
  G.dirty = true;
}
function groundY(x, z, fallback) {
  const T = S.terrain; if (!T) return fallback;
  const n = T.n, c = Math.floor((x - T.min[0]) / (T.max[0] - T.min[0]) * n), r = Math.floor((z - T.min[2]) / (T.max[2] - T.min[2]) * n);
  if (c < 0 || r < 0 || c >= n || r >= n) return fallback;
  return T.h[r * n + c];
}

// Spots: a translucent pad hugging the ground, an outline, and a pin.
function buildSlots() {
  const T3 = G.three; if (!T3 || !S.work) return;
  clearGroup(T3.groups.markers); G.pickable = [];
  T3.groups.markers.visible = S.showSpots;
  const pads = { pos: [], col: [] }, lines = { pos: [], col: [] }, pins = { pos: [], col: [] };
  const ink = hexRgb(cssVar("--ink")), warn = hexRgb(cssVar("--warn"));
  for (const s of S.work.slots) {
    if (!visibleSlot(s)) continue;
    const [v, op, em] = slotLook(s), rgb = hexRgb(cssVar(v)), sel = S.slot === s.id, ch = slotChanged(s);
    const [x, y, z] = s.pos, half = parseFloat(s.group) / 2 || 3, seg = Math.max(1, Math.round(half / 4));
    const P = (px, pz) => [px, groundY(px, pz, y) + 0.45, pz];
    const pa = (S.models ? 0.22 : 0.38) * op + (sel ? 0.25 : 0);
    for (let a = 0; a < seg; a++) for (let b = 0; b < seg; b++) {
      const x0 = x - half + 2 * half * a / seg, x1 = x - half + 2 * half * (a + 1) / seg;
      const z0 = z - half + 2 * half * b / seg, z1 = z - half + 2 * half * (b + 1) / seg;
      for (const q of [[x0, z0], [x1, z0], [x0, z1], [x1, z0], [x1, z1], [x0, z1]]) { pads.pos.push(...P(q[0], q[1])); pads.col.push(...rgb, pa); }
    }
    const edge = sel ? ink : ch ? warn : rgb, ea = sel || ch ? 1 : 0.5 + 0.5 * op;
    const cs = [[x - half, z - half], [x + half, z - half], [x + half, z + half], [x - half, z + half]];
    for (let q = 0; q < 4; q++) {
      const A = cs[q], B = cs[(q + 1) % 4];
      for (let t = 0; t < seg; t++) {
        const f0 = t / seg, f1 = (t + 1) / seg;
        lines.pos.push(...P(A[0] + (B[0] - A[0]) * f0, A[1] + (B[1] - A[1]) * f0), ...P(A[0] + (B[0] - A[0]) * f1, A[1] + (B[1] - A[1]) * f1));
        lines.col.push(...edge, ea, ...edge, ea);
      }
    }
    const h = (4 + Math.sqrt(half) * 2.2) * (0.45 + em) * (sel ? 1.6 : 1), w = sel ? 1.4 : 0.9, top = y + h;
    const pc = sel ? ink : rgb;
    const quads = [[[w, -w], [w, w]], [[-w, w], [-w, -w]], [[w, w], [-w, w]], [[-w, -w], [w, -w]]];
    for (const [[ax, az], [bx, bz]] of quads) {
      for (const [qx, qy, qz] of [[ax, y, az], [bx, y, bz], [bx, top, bz], [ax, y, az], [bx, top, bz], [ax, top, az]]) { pins.pos.push(x + qx, qy, z + qz); pins.col.push(...pc); }
    }
    for (const [qx, qz] of [[-w, -w], [w, -w], [w, w], [-w, -w], [w, w], [-w, w]]) { pins.pos.push(x + qx, top, z + qz); pins.col.push(...pc.map(c => Math.min(1, c * 1.2))); }
    G.pickable.push({ id: s.id, x, z: -z, base: y, top });
  }
  const geo = (p, c, size) => { const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(p, 3)); g.setAttribute("color", new THREE.Float32BufferAttribute(c, size)); return g; };
  const padMesh = new THREE.Mesh(geo(pads.pos, pads.col, 4), new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -4, toneMapped: false }));
  padMesh.renderOrder = 3;
  const lineMesh = new THREE.LineSegments(geo(lines.pos, lines.col, 4), new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false, toneMapped: false }));
  lineMesh.renderOrder = 4;
  const pinGeo = geo(pins.pos, pins.col, 3); pinGeo.computeVertexNormals();
  const pinMesh = new THREE.Mesh(pinGeo, new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide }));
  T3.groups.markers.add(padMesh, lineMesh, pinMesh);
  G.dirty = true;
}

// ---- models -----------------------------------------------------------------
// A glb from data/uncooked holds one or more submeshes (POSITION, NORMAL,
// TEXCOORD_0, indices) plus an "AABB" helper node, which is skipped.
function parseGlb(buf) {
  const dv = new DataView(buf), jsonLen = dv.getUint32(12, true);
  const json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jsonLen)));
  const binStart = 20 + jsonLen + 8;
  const TYPES = { 5126: Float32Array, 5125: Uint32Array, 5123: Uint16Array, 5121: Uint8Array };
  const SIZE = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };
  const read = (i) => {
    const a = json.accessors[i], bv = json.bufferViews[a.bufferView], T = TYPES[a.componentType], n = a.count * SIZE[a.type];
    const start = binStart + (bv.byteOffset || 0) + (a.byteOffset || 0);
    return new T(buf.slice(start, start + n * T.BYTES_PER_ELEMENT));
  };
  const pos = [], nrm = [], uv = [], idx = []; let base = 0;
  for (const node of json.nodes || []) {
    if (node.mesh == null || node.name === "AABB") continue;
    for (const prim of json.meshes[node.mesh].primitives) {
      if (prim.attributes.POSITION == null) continue;
      const p = read(prim.attributes.POSITION), count = p.length / 3;
      pos.push(p);
      nrm.push(prim.attributes.NORMAL != null ? read(prim.attributes.NORMAL) : new Float32Array(count * 3));
      uv.push(prim.attributes.TEXCOORD_0 != null ? read(prim.attributes.TEXCOORD_0) : new Float32Array(count * 2));
      const ix = prim.indices != null ? read(prim.indices) : Uint32Array.from({ length: count }, (_, i) => i);
      idx.push(Uint32Array.from(ix, v => v + base)); base += count;
    }
  }
  const cat = (arrs, T) => { const out = new T(arrs.reduce((a, x) => a + x.length, 0)); let o = 0; for (const x of arrs) { out.set(x, o); o += x.length; } return out; };
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(cat(pos, Float32Array), 3));
  g.setAttribute("normal", new THREE.BufferAttribute(cat(nrm, Float32Array), 3));
  g.setAttribute("uv", new THREE.BufferAttribute(cat(uv, Float32Array), 2));
  g.setIndex(new THREE.BufferAttribute(cat(idx, Uint32Array), 1));
  g.computeBoundingSphere();
  return g;
}
const fileUrl = (rel) => "/api/file?path=" + encodeURIComponent(rel);
const queue = { active: 0, waiting: [] };
function limited(fn) {
  return new Promise((res, rej) => {
    const run = () => { queue.active++; fn().then(res, rej).finally(() => { queue.active--; const nx = queue.waiting.shift(); if (nx) nx(); }); };
    queue.active < 6 ? run() : queue.waiting.push(run);
  });
}
async function loadTexture(rel, swap) {
  const img = await limited(() => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = fileUrl(rel); }));
  let tex;
  if (swap) {   // the png was written from an uncompressed texture with red and blue swapped
    const cv = document.createElement("canvas"); cv.width = img.width; cv.height = img.height;
    const ctx = cv.getContext("2d"); ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, cv.width, cv.height);
    for (let i = 0; i < d.data.length; i += 4) { const r = d.data[i]; d.data[i] = d.data[i + 2]; d.data[i + 2] = r; }
    ctx.putImageData(d, 0, 0); tex = new THREE.CanvasTexture(cv);
  } else {
    tex = new THREE.Texture(img); tex.needsUpdate = true;
  }
  tex.colorSpace = THREE.SRGBColorSpace; tex.flipY = false; tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = Math.min(8, G.three.renderer.capabilities.getMaxAnisotropy());
  return tex;
}
const partKey = (p) => [p.mesh, p.texture || "", p.swap_rb, p.color || "", p.decal].join("|");
let DECAL_GEO = null;   // decals: the texture on a 1 m quad lying in the cube's XZ plane
function partAsset(p) {
  const key = partKey(p);
  let a = G.parts.get(key);
  if (!a) {
    G.loading++;
    a = { geometry: null, material: null };
    if (p.decal && !DECAL_GEO) DECAL_GEO = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
    a.ready = Promise.all([
      p.decal ? Promise.resolve(DECAL_GEO)
        : limited(() => fetch(fileUrl(p.mesh)).then(r => { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); })).then(parseGlb),
      p.texture ? loadTexture(p.texture, p.swap_rb).catch(() => null) : Promise.resolve(null),
    ]).then(([geo, tex]) => {
      a.geometry = geo;
      if (p.decal) {
        if (!tex) return null;
        a.material = new THREE.MeshStandardMaterial({ map: tex, transparent: true, depthWrite: false, roughness: 1,
          polygonOffset: true, polygonOffsetFactor: -2, side: THREE.DoubleSide });
        a.decal = true;
      } else {
        a.material = new THREE.MeshStandardMaterial({ map: tex, color: tex ? 0xffffff : (p.color || 0xb5ad9c),
          roughness: 0.88, metalness: 0, alphaTest: 0.4, side: THREE.DoubleSide });
      }
      return a;
    }).catch(() => null).finally(() => { G.loaded++; progress(); });
    G.parts.set(key, a);
  }
  return a;
}
function progress() {
  const busy = G.loaded < G.loading;
  $("load").textContent = busy ? `Loading models ${G.loaded}/${G.loading}…` : "";
  $("load").hidden = !busy;
}
const b64f32 = (s) => { const raw = Uint8Array.from(atob(s), c => c.charCodeAt(0)); return new Float32Array(raw.buffer); };
// Draw a batch of {parts, matrices} payloads (each with an optional offset)
// into `group` as one InstancedMesh per distinct mesh+texture.
async function fillGroup(group, batches, token) {
  const per = new Map();
  for (const { data, offset } of batches) {
    data.parts.forEach((p, i) => {
      const key = partKey(p);
      let e = per.get(key); if (!e) per.set(key, e = { part: p, mats: [] });
      const m = b64f32(data.matrices[i]);
      if (offset) for (let j = 0; j < m.length; j += 16) { m[j + 12] += offset[0]; m[j + 13] += offset[1]; m[j + 14] += offset[2]; }
      e.mats.push(m);
    });
  }
  const meshes = [];
  await Promise.all([...per.values()].map(async ({ part, mats }) => {
    const a = await partAsset(part).ready; if (!a) return;
    const count = mats.reduce((s, m) => s + m.length / 16, 0);
    const im = new THREE.InstancedMesh(a.geometry, a.material, count);
    let o = 0; for (const m of mats) { im.instanceMatrix.array.set(m, o); o += m.length; }
    im.instanceMatrix.needsUpdate = true; im.computeBoundingSphere();
    im.castShadow = !a.decal; im.receiveShadow = true; im.userData.shared = true;
    if (a.decal) im.renderOrder = 1;
    meshes.push(im);
  }));
  if (token !== group.userData.token) return;   // a newer fill replaced this one
  clearGroup(group); for (const m of meshes) group.add(m);
  G.dirty = true;
}
async function loadScenery(key) {
  if (!G.three) return;
  const g = G.three.groups.scenery; g.userData.token = key; clearGroup(g);
  try {
    const data = await api("/api/scene?chapter=" + encodeURIComponent(key));
    if (S.chapter.key !== key) return;
    S.sceneInfo = `${data.instances.toLocaleString()} objects`;
    await fillGroup(g, [{ data }], key);
  } catch (err) { S.sceneInfo = null; S.modelsError = err.message; }
  renderLegend();
}
async function tileData(path) {
  if (!G.tileCache.has(path)) G.tileCache.set(path, api(`/api/tile?chapter=${encodeURIComponent(S.chapter.key)}&path=${encodeURIComponent(path)}`).catch(() => null));
  return G.tileCache.get(path);
}
async function drawLayout() {
  if (!G.three) return;
  const g = G.three.groups.tiles, token = {}; g.userData.token = token;
  const batches = [];
  for (const [id, path] of Object.entries(S.layout)) {
    const s = S.work.slots.find(x => String(x.id) === id); const data = await tileData(path);
    if (s && data && data.instances) batches.push({ data, offset: s.pos });
  }
  if (g.userData.token !== token) return;
  if (!batches.length) { clearGroup(g); G.dirty = true; return; }
  await fillGroup(g, batches, token);
}

// A rough stand-in for the generator, for looking at, not for balancing: each
// kind in order takes random eligible spots it keeps its spacing on, and a
// pool tile whose flags match the kind and whose size matches the spot,
// weighted by tile weight, within the flag limits.
function sampleLayout(seed) {
  let a = seed >>> 0; const rnd = () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const used = new Set(), placed = [], quota = S.work.quotas.map(() => 0), out = {};
  for (const k of S.work.kinds) {
    const spots = S.work.slots.filter(s => eligible(s, k) === "yes" && !used.has(s.id));
    for (let i = spots.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [spots[i], spots[j]] = [spots[j], spots[i]]; }
    let n = 0;
    for (const s of spots) {
      if (n >= k.count) break;
      if (placed.some(p => p.kind === k.name && Math.hypot(p.pos[0] - s.pos[0], p.pos[2] - s.pos[2]) < k.min_distance)) continue;
      const fits = S.pool.filter(t => `${t.width}x${t.height}` === s.group
        && k.required.every(f => t.flags.includes(f)) && !k.excluded.some(f => t.flags.includes(f))
        && S.work.quotas.every((q, qi) => !q.flags.every(f => t.flags.includes(f)) || quota[qi] < q.limit));
      if (!fits.length) continue;
      const total = fits.reduce((w, t) => w + (t.weight > 0 ? t.weight : 1), 0);
      let r = rnd() * total, tile = fits[fits.length - 1];
      for (const t of fits) { r -= t.weight > 0 ? t.weight : 1; if (r <= 0) { tile = t; break; } }
      S.work.quotas.forEach((q, qi) => { if (q.flags.every(f => tile.flags.includes(f))) quota[qi]++; });
      used.add(s.id); placed.push({ kind: k.name, pos: s.pos }); out[String(s.id)] = tile.path; n++;
    }
  }
  return out;
}
function frame() {
  requestAnimationFrame(frame);
  const T3 = G.three, cv = $("gl");
  if (!T3 || S.view !== "3d" || !G.dirty) return;
  const w = cv.clientWidth, h = cv.clientHeight; if (!w || !h) return;
  const size = T3.renderer.getSize(new THREE.Vector2());
  if (size.x !== w || size.y !== h) T3.renderer.setSize(w, h, false);
  G.dirty = false;
  const c = G.cam, cp = Math.cos(c.pitch);
  T3.camera.aspect = w / h;
  T3.camera.position.set(c.tx + c.dist * cp * Math.sin(c.yaw), c.ty + c.dist * Math.sin(c.pitch), c.tz + c.dist * cp * Math.cos(c.yaw));
  T3.camera.lookAt(c.tx, c.ty, c.tz); T3.camera.updateProjectionMatrix(); T3.camera.updateMatrixWorld();
  T3.scene.background = new THREE.Color(cssVar("--panel"));
  T3.groups.scenery.visible = T3.groups.tiles.visible = S.models;
  T3.renderer.render(T3.scene, T3.camera);
}
function project(p) {
  const T3 = G.three, cv = $("gl"); if (!T3) return null;
  const v = new THREE.Vector3(p[0], p[1], p[2]), d = v.distanceTo(T3.camera.position);
  v.project(T3.camera); if (v.z > 1) return null;
  return [(v.x * 0.5 + 0.5) * cv.clientWidth, (1 - (v.y * 0.5 + 0.5)) * cv.clientHeight, d];
}
function pickAt(mx, my) {
  let best = null;
  for (const p of G.pickable || []) {
    const a = project([p.x, p.base, p.z]), b = project([p.x, p.top, p.z]); if (!a || !b) continue;
    const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((mx - a[0]) * dx + (my - a[1]) * dy) / L));
    const d = Math.hypot(mx - (a[0] + t * dx), my - (a[1] + t * dy));
    if (d < 14 && (!best || d + a[2] * 0.002 < best.score)) best = { id: p.id, score: d + a[2] * 0.002 };
  }
  return best && best.id;
}
function resetCamera() {
  const slots = S.work ? S.work.slots.filter(s => !s.whole_map) : [];
  const cx = slots.length ? slots.reduce((a, s) => a + s.pos[0], 0) / slots.length : 0;
  const cz = slots.length ? slots.reduce((a, s) => a + s.pos[2], 0) / slots.length : 0;
  Object.assign(G.cam, { tx: cx, ty: 0, tz: -cz, yaw: 0, pitch: 0.95, dist: 640 });
  G.dirty = true;
}
function bindCamera(cv) {
  let drag = null; const pointers = new Map();
  cv.addEventListener("contextmenu", e => e.preventDefault());
  cv.addEventListener("pointerdown", e => {
    cv.setPointerCapture(e.pointerId); pointers.set(e.pointerId, [e.clientX, e.clientY]);
    drag = { x: e.clientX, y: e.clientY, moved: 0, pan: e.button === 2 || e.shiftKey, pinch: pointers.size === 2 ? null : undefined };
    cv.classList.add("dragging");
  });
  cv.addEventListener("pointermove", e => {
    const r = cv.getBoundingClientRect();
    if (!drag) { const id = pickAt(e.clientX - r.left, e.clientY - r.top);
      if (id != null) showTip(e, S.work.slots.find(s => s.id === id)); else $("tip").hidden = true; return; }
    const prev = pointers.get(e.pointerId); pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 2) {
      const [p1, p2] = [...pointers.values()], d = Math.hypot(p1[0] - p2[0], p1[1] - p2[1]);
      if (drag.pinch) G.cam.dist = Math.max(40, Math.min(1600, G.cam.dist * drag.pinch / d));
      drag.pinch = d; drag.moved += 10; G.dirty = true; return;
    }
    const dx = e.clientX - (prev ? prev[0] : drag.x), dy = e.clientY - (prev ? prev[1] : drag.y);
    drag.moved += Math.abs(dx) + Math.abs(dy);
    const c = G.cam;
    if (drag.pan) {
      const k = c.dist * 0.0016, sy = Math.sin(c.yaw), cy = Math.cos(c.yaw);
      c.tx -= (cy * dx + sy * dy) * k; c.tz += (sy * dx - cy * dy) * k;   // grab the ground
    } else {
      c.yaw -= dx * 0.006; c.pitch = Math.max(0.12, Math.min(1.5605, c.pitch + dy * 0.005));
    }
    G.dirty = true; $("tip").hidden = true;
  });
  const end = e => {
    pointers.delete(e.pointerId);
    if (drag && drag.moved < 5 && pointers.size === 0) {
      const r = cv.getBoundingClientRect(), id = pickAt(e.clientX - r.left, e.clientY - r.top);
      if (id != null) pickSlot(id);
    }
    if (pointers.size === 0) { drag = null; cv.classList.remove("dragging"); }
  };
  cv.addEventListener("pointerup", end); cv.addEventListener("pointercancel", end);
  cv.addEventListener("wheel", e => { e.preventDefault(); G.cam.dist = Math.max(40, Math.min(1600, G.cam.dist * Math.exp(e.deltaY * 0.0012))); G.dirty = true; }, { passive: false });
  cv.addEventListener("mouseleave", () => { $("tip").hidden = true; });
}

// ---- map chrome shared by both views ----------------------------------------
function showTip(ev, s) {
  if (!s) return;
  const tip = $("tip"), r = $("viewport").getBoundingClientRect();
  const kind = S.kind != null ? S.work.kinds[S.kind] : null;
  let line;
  if (kind) {
    const e = eligible(s, kind);
    line = e === "yes" ? `${nice(kind.name)} can go here` : e === "blocked" ? `allows ${nice(kind.name)}, but it doesn't fit ${sizeLabel(s.group)}` : `${nice(kind.name)} not allowed here`;
  } else {
    const f = fitsNow(s).map(k => nice(k.name));
    line = f.length ? `can hold: ${f.slice(0, 4).join(", ")}${f.length > 4 ? ` +${f.length - 4}` : ""}` : "holds nothing in this scenario";
  }
  const shown = S.layout[String(s.id)];
  tip.innerHTML = `<b>Spot ${s.id}</b> · ${esc(sizeLabel(s.group))}<br>${esc(line)}` +
    (shown ? `<br><span class="muted">showing ${esc(nice(shown.split("\\").pop().replace(".tiledef.ot", "")))}</span>` : "");
  tip.hidden = false;
  const x = ev.clientX - r.left + 14, y = ev.clientY - r.top + 14;
  tip.style.left = Math.min(x, r.width - tip.offsetWidth - 6) + "px"; tip.style.top = Math.min(y, r.height - tip.offsetHeight - 6) + "px";
}
function pickSlot(id) { S.slot = id; setTab("slot"); render(); }
function renderLegend() {
  const kind = S.kind != null ? S.work.kinds[S.kind] : null;
  const sw = (v, op) => `<i class="sw" style="background:var(${v});opacity:${op}"></i>`;
  let h;
  if (kind) {
    h = `<b>${esc(nice(kind.name))}</b><span>${eligibleCount(kind)} spots where it can go</span>` +
      `<span>${sw("--ok", 1)}can go here</span><span>${sw("--warn", .8)}allowed, wrong size</span>` +
      (S.showAll ? `<span>${sw("--idle", .5)}not allowed</span>` : "") +
      `<span><button class="small" id="clearkind">Show all tiles</button></span>`;
  } else {
    h = `<b>Spot sizes</b>` + S.work.groups.map(g => `<span>${sw(groupVar(g.name), .9)}${esc(sizeLabel(g.name))} · ${g.slots.length}</span>`).join("") +
      `<span class="muted">Pick a tile to see where it goes</span>`;
  }
  if (S.terrain) h += `<span class="muted" style="margin-top:4px"><i class="sw" style="background:#d9b878"></i>design paths <i class="sw" style="background:#3a78b6;margin-left:6px"></i>water</span>`;
  if (S.view === "3d" && S.models) {
    const nt = Object.keys(S.layout).length;
    if (S.sceneInfo) h += `<span class="muted">Scenery: ${esc(S.sceneInfo)}</span>`;
    else if (S.modelsError) h += `<span class="warn" title="${esc(S.modelsError)}">No models: run scripts/extract_uncooked.py</span>`;
    if (nt) h += `<span class="muted">Tiles shown on ${nt} spots${S.layoutSample ? " (sample, approximate)" : ""}</span>`;
  }
  $("legend").innerHTML = h;
  const b = $("clearkind"); if (b) b.addEventListener("click", () => { S.kind = null; render(); });
}
function setView(v) {
  if (v === "3d" && !G.three) v = "2d";
  S.view = v;
  $("v3d").setAttribute("aria-pressed", String(v === "3d")); $("v2d").setAttribute("aria-pressed", String(v === "2d"));
  // toggleAttribute, not .hidden: an SVG element has no `hidden` property.
  $("gl").toggleAttribute("hidden", v !== "3d"); $("map").toggleAttribute("hidden", v !== "2d");
  for (const id of ["recenter", "sample"]) $(id).hidden = v !== "3d";
  for (const id of ["models", "spots"]) $(id).parentElement.hidden = v !== "3d";
  $("clearlayout").hidden = v !== "3d" || !Object.keys(S.layout).length;
  $("hint").textContent = v === "3d" ? "Drag to rotate · right-drag or Shift-drag to pan · scroll to zoom · click a spot"
                                     : "Click a spot to edit it";
  G.dirty = true; store.set("rsmm.mapeditor.view", v);
}

// ---- panels -----------------------------------------------------------------
function setTab(t) {
  S.tab = t;
  document.querySelectorAll("[data-tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
}
function undoBtn(attr) { return `<button class="undo" title="Back to the shipped value" ${attr}>↺</button>`; }
function helpBox() {
  const open = store.get("rsmm.mapeditor.help") !== "closed" ? "open" : "";
  return `<details class="help" id="help" ${open}><summary>How map generation works</summary><ul>
    <li><b>Spots</b> are fixed places on the map where a tile can be put. Each spot has a size (for example 40×40 m).</li>
    <li><b>Tiles</b> are what fills them: camps, shrines, the start, the boss arena. For each tile you set how many a run gets, how far apart they must be, and which spot sizes it fits.</li>
    <li>A tile can only go on a spot that <b>allows it</b> (see the Spot tab) <b>and</b> whose size it fits.</li>
    <li><b>Limits</b> cap special tiles (at most one Wishing Well, …) however the counts work out.</li>
    <li>The game picks one <b>scenario</b> per run. A scenario can force a tile onto, or keep it off, particular spots, so switch scenarios to see each case.</li>
    <li>When you're done, <b>Review &amp; save</b> writes a normal mod you install with <code>rsmm apply</code>.</li>
  </ul></details>`;
}
function renderKinds() {
  const groups = S.work.groups.map(g => g.name), q = S.filter.toLowerCase();
  let h = helpBox() + `<div class="toolbar"><input type="search" id="kfilter" placeholder="Find a tile…" value="${esc(S.filter)}" aria-label="Filter tiles">
    <span class="muted">${S.work.kinds.length} tile types</span></div>`;
  h += `<table><thead><tr><th>Tile</th><th title="How many the generator tries to place each run">Per run</th><th title="Minimum distance between two of this tile">Spacing (m)</th><th title="Spots it could go on in this scenario — click to show them">Spots</th></tr></thead>`;
  S.work.kinds.forEach((k, i) => {
    if (q && !nice(k.name).toLowerCase().includes(q)) return;
    const o = S.orig.kinds[i], n = eligibleCount(k), sel = S.kind === i ? "sel" : "";
    const cCh = k.count !== o.count, dCh = Math.abs(k.min_distance - o.min_distance) > 1e-4;
    const fp = groups.map(g => {
      const ch = k.footprints[g] !== o.footprints[g];
      return `<label class="chipbox ${ch ? "changed" : ""}"><input type="checkbox" data-k="${i}" data-fp="${esc(g)}" ${k.footprints[g] ? "checked" : ""}>${esc(sizeLabel(g))}</label>`;
    }).join("");
    const short = k.count > n;
    h += `<tbody class="kind ${sel}"><tr>
      <td class="kname" data-pick="${i}" title="Show on the map">${esc(nice(k.name))}</td>
      <td class="${cCh ? "changed" : ""}"><input type="number" min="0" max="500" step="1" data-k="${i}" data-f="count" value="${k.count}" aria-label="${esc(nice(k.name))} per run">${cCh ? undoBtn(`data-undo="${i}" data-uf="count"`) : ""}</td>
      <td class="${dCh ? "changed" : ""}"><input type="number" min="0" max="2000" step="1" data-k="${i}" data-f="min_distance" value="${k.min_distance}" aria-label="${esc(nice(k.name))} spacing">${dCh ? undoBtn(`data-undo="${i}" data-uf="min_distance"`) : ""}</td>
      <td><span class="badge ${short ? "warn" : ""}" data-pick="${i}" title="${short ? "Asks for more than there are spots — some won't be placed" : "Show these spots"}">${n}</span></td></tr>
      <tr><td colspan="4"><div class="fp"><span>fits</span>${fp}</div></td></tr></tbody>`;
  });
  h += `</table><p class="muted">Spacing and limits can still leave fewer placed than “per run” asks for.</p>`;
  $("panel").innerHTML = h;
  const P = $("panel");
  $("help").addEventListener("toggle", e => store.set("rsmm.mapeditor.help", e.target.open ? "open" : "closed"));
  $("kfilter").addEventListener("input", e => { S.filter = e.target.value; const pos = e.target.selectionStart; renderKinds(); const f = $("kfilter"); f.focus(); f.setSelectionRange(pos, pos); });
  P.querySelectorAll("[data-pick]").forEach(el => el.addEventListener("click", () => {
    const i = Number(el.dataset.pick); S.kind = S.kind === i ? null : i; render();
  }));
  P.querySelectorAll("input[data-f]").forEach(el => el.addEventListener("change", () => {
    const k = S.work.kinds[Number(el.dataset.k)], v = Number(el.value), max = Number(el.max);
    if (!Number.isFinite(v) || v < 0 || v > max) { el.value = k[el.dataset.f]; status(`Use a number from 0 to ${max}.`, "bad"); return; }
    k[el.dataset.f] = el.dataset.f === "count" ? Math.round(v) : v; render();
  }));
  P.querySelectorAll("input[data-fp]").forEach(el => el.addEventListener("change", () => {
    S.work.kinds[Number(el.dataset.k)].footprints[el.dataset.fp] = el.checked; render();
  }));
  P.querySelectorAll("[data-undo]").forEach(el => el.addEventListener("click", () => {
    const i = Number(el.dataset.undo); S.work.kinds[i][el.dataset.uf] = S.orig.kinds[i][el.dataset.uf]; render();
  }));
}
function renderQuotas() {
  let h = `<p class="muted">A hard cap on tiles that carry a flag, applied after the per-run counts. Useful to allow more shrines, or a second Wishing Well.</p>`;
  h += `<table><thead><tr><th>Tiles flagged</th><th>At most</th></tr></thead><tbody>`;
  S.work.quotas.forEach((q, i) => {
    const ch = q.limit !== S.orig.quotas[i].limit;
    h += `<tr><td>${esc(nice(q.flags.join(" + ")))}</td><td class="${ch ? "changed" : ""}"><input type="number" min="0" max="500" step="1" data-q="${i}" value="${q.limit}" aria-label="${esc(q.key)} limit">${ch ? undoBtn(`data-uq="${i}"`) : ""}</td></tr>`;
  });
  h += `</tbody></table>`;
  $("panel").innerHTML = h;
  $("panel").querySelectorAll("input[data-q]").forEach(el => el.addEventListener("change", () => {
    const q = S.work.quotas[Number(el.dataset.q)], v = Math.round(Number(el.value));
    if (!Number.isFinite(v) || v < 0 || v > 500) { el.value = q.limit; status("Use a number from 0 to 500.", "bad"); return; }
    q.limit = v; render();
  }));
  $("panel").querySelectorAll("[data-uq]").forEach(el => el.addEventListener("click", () => {
    const i = Number(el.dataset.uq); S.work.quotas[i].limit = S.orig.quotas[i].limit; render();
  }));
}
function renderSlot() {
  const s = S.work.slots.find(x => x.id === S.slot);
  if (!s) { $("panel").innerHTML = `<p class="muted">Click a spot on the map to see which tiles it can hold, and change that.</p>`; return; }
  const o = S.orig.slots.find(x => x.id === s.id);
  const ground = S.terrain ? groundY(s.pos[0], s.pos[2], null) : null;
  let h = `<div class="slotinfo"><span class="muted">Spot</span><span><b>${s.id}</b></span>
    <span class="muted">Size</span><span>${esc(sizeLabel(s.group))}</span>
    <span class="muted">Position</span><span>x ${s.pos[0].toFixed(1)}, z ${s.pos[2].toFixed(1)}, height ${s.pos[1].toFixed(1)} m</span></div>`;
  if (s.whole_map) {
    h += `<p class="muted">A whole-map spot: it lists no tiles (that is what makes it one), so there is nothing to edit.</p>`;
    $("panel").innerHTML = h; return;
  }
  const ov = s.overrides[S.scen] || {};
  // Three groups, most useful first: what can land here, what would fit if
  // allowed, and what is the wrong size for this spot anyway (collapsed).
  const now = [], off = [], size = [];
  S.work.kinds.forEach(k => {
    const e = eligible(s, k);
    (e === "yes" ? now : k.footprints[s.group] ? off : size).push(k);
  });
  const row = (k, fitBtn) => {
    const ch = s.allow[k.name] !== o.allow[k.name];
    let note = "";
    if (ov[k.name] === 1) note = `<span class="muted" title="This scenario puts it here regardless of the tick">· forced on in this scenario</span>`;
    else if (ov[k.name] === 0) note = `<span class="muted" title="This scenario keeps it off regardless of the tick">· kept off in this scenario</span>`;
    if (fitBtn) note += ` <button class="small" data-fit="${esc(k.name)}" title="Tick ${esc(sizeLabel(s.group))} for ${esc(nice(k.name))} on every spot">Let it fit</button>`;
    return `<label class="${ch ? "changed" : ""}"><input type="checkbox" data-allow="${esc(k.name)}" ${s.allow[k.name] ? "checked" : ""}> <span>${esc(nice(k.name))} ${note}</span></label>`;
  };
  h += `<h3 class="okc">Can go here now (${now.length})</h3><div class="kgrid">${now.map(k => row(k, false)).join("") || `<span class="muted">nothing in this scenario</span>`}</div>`;
  if (off.length) h += `<h3>Right size, but not allowed here (${off.length})</h3><div class="kgrid">${off.map(k => row(k, false)).join("")}</div>`;
  if (size.length) h += `<details><summary class="muted">Wrong size for a ${esc(sizeLabel(s.group))} spot (${size.length})</summary><div class="kgrid">${size.map(k => row(k, true)).join("")}</div></details>`;
  h += `<p class="muted">Tick a tile to allow it on this spot. A tile also has to fit the spot's size, which is set per tile in the Tiles tab.</p>`;
  const fitTiles = S.pool.filter(t => `${t.width}x${t.height}` === s.group
    && now.some(k => k.required.every(f => t.flags.includes(f)) && !k.excluded.some(f => t.flags.includes(f))));
  if (G.three) {
    const cur = S.layout[String(s.id)] || "";
    h += `<h3>Preview a tile here</h3><div class="toolbar"><select id="preview" aria-label="Tile to preview on this spot"><option value="">— none —</option>` +
      fitTiles.map(t => `<option value="${esc(t.path)}" ${t.path === cur ? "selected" : ""}>${esc(nice(t.name))}</option>`).join("") +
      `</select><span class="muted">${fitTiles.length} tile${fitTiles.length === 1 ? "" : "s"} in this chapter's pool can land here now</span></div>`;
  }
  $("panel").innerHTML = h;
  $("panel").querySelectorAll("input[data-allow]").forEach(el => el.addEventListener("change", () => {
    s.allow[el.dataset.allow] = el.checked; render();
  }));
  const pv = $("preview"); if (pv) pv.addEventListener("change", () => {
    if (pv.value) S.layout[String(s.id)] = pv.value; else delete S.layout[String(s.id)];
    S.layoutSample = false; drawLayout(); setView(S.view); render();
  });
  $("panel").querySelectorAll("[data-fit]").forEach(el => el.addEventListener("click", (e) => {
    e.preventDefault(); S.work.kinds.find(k => k.name === el.dataset.fit).footprints[s.group] = true; render();
  }));
}
function renderChanges() {
  const list = changeList();
  let h = list.length
    ? `<h3>${list.length} change${list.length === 1 ? "" : "s"} to ${esc(S.chapter.label)}</h3><ul class="changes">${list.map((c, i) => `<li><span>${esc(c.text)}</span>${undoBtn(`data-uc="${i}"`)}</li>`).join("")}</ul>`
    : `<p class="muted">No changes yet. Everything matches the game's own recipe.</p>`;
  h += `<h3>Save as a mod</h3><div class="form">
    <label for="modid">Mod id</label><input id="modid" type="text" placeholder="my-map-tweaks" value="${esc($("modid-keep").value)}">
    <label for="modname">Name</label><input id="modname" type="text" placeholder="optional" value="${esc($("modname-keep").value)}"></div>
    <div class="toolbar"><button id="check">Check</button><button id="reset">Undo everything</button><button id="save" class="primary" ${list.length ? "" : "disabled"}>Save mod</button></div>`;
  if (S.lastSave) {
    h += `<h3 class="okc">Saved ${esc(S.lastSave.path)}</h3><p>Close the game, then install it with:</p>
      <pre class="cmd" id="cmd">${esc(S.lastSave.next)}</pre><button class="small" id="copy">Copy</button>
      <p class="muted">Map generation mods are experimental: play a run and check it before sharing.</p>`;
  }
  $("panel").innerHTML = h;
  $("panel").querySelectorAll("[data-uc]").forEach(el => el.addEventListener("click", () => { list[Number(el.dataset.uc)].undo(); render(); }));
  for (const id of ["modid", "modname"]) $(id).addEventListener("input", e => { $(id + "-keep").value = e.target.value; });
  $("check").addEventListener("click", doCheck);
  $("save").addEventListener("click", doSave);
  $("reset").addEventListener("click", () => {
    if (changeList().length && !confirm("Undo every change back to the game's own recipe?")) return;
    S.work = clone(S.orig); render(); status("Back to the game's own recipe");
  });
  const cp = $("copy"); if (cp) cp.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(S.lastSave.next); status("Copied", "ok"); } catch (e) { status("Copy failed; select the text instead.", "bad"); }
  });
}
function render() {
  if (!S.work) return;
  renderLegend();
  if (S.view === "2d") renderMap();
  buildTerrain(); buildSlots();
  ({ kinds: renderKinds, quotas: renderQuotas, slot: renderSlot, changes: renderChanges })[S.tab]();
  const n = changeList().length;
  $("nchanges").textContent = n ? `(${n})` : "";
  const hs = new URLSearchParams({ chapter: S.chapter.key, scenario: String(S.scen), view: S.view });
  if (S.kind != null) hs.set("kind", S.work.kinds[S.kind].name);
  history.replaceState(null, "", "#" + hs.toString());
}

// ---- actions ----------------------------------------------------------------
async function loadTerrain(key) {
  try {
    const t = decodeTerrain(await api("/api/terrain?grid=512&chapter=" + encodeURIComponent(key)));
    if (S.chapter.key !== key) return;
    t.imageUrl = await terrainImage(t);
    S.terrain = t; G.terrainKey = null; render();
  } catch (err) {
    S.terrain = null;
    status(`No terrain for ${key} (${err.message}). Spots are still editable.`, "bad");
    render();
  }
}
async function loadChapter(key, initialEdits) {
  status("Loading " + key + "…");
  const data = await api("/api/recipe?chapter=" + encodeURIComponent(key));
  if (S.terrain && S.terrain.imageUrl) URL.revokeObjectURL(S.terrain.imageUrl);
  S.chapter = data.chapter; S.orig = data.recipe; S.work = clone(data.recipe);
  S.kind = null; S.slot = null; S.scen = 0; S.terrain = null; S.lastSave = null; G.terrainKey = null;
  S.layout = {}; S.layoutSample = false; S.pool = []; S.sceneInfo = null; S.modelsError = null; G.tileCache.clear();
  if (G.three) { clearGroup(G.three.groups.tiles); G.three.groups.tiles.userData.token = null; }
  $("scenario").innerHTML = S.orig.scenarios.map((sc, i) => `<option value="${i}">${esc(sc.id)} · ${esc(sc.label)}</option>`).join("");
  $("scenario").disabled = S.orig.scenarios.length < 2;
  if (initialEdits) applyEdits(initialEdits);
  $("chapter").value = key; $("maptitle").textContent = data.chapter.label;
  resetCamera(); render();
  status(`${data.chapter.label}: ${S.orig.kinds.length} tile types, ${S.orig.slots.filter(s => !s.whole_map).length} spots`);
  loadTerrain(key);
  api("/api/tiles?chapter=" + encodeURIComponent(key)).then(r => { if (S.chapter.key === key) { S.pool = r.tiles; render(); } }).catch(() => {});
  if (G.three && S.models) loadScenery(key);
}
function applyEdits(e) {
  for (const [n, d] of Object.entries(e.kinds || {})) {
    const k = S.work.kinds.find(x => x.name === n); if (!k) continue;
    if ("count" in d) k.count = d.count;
    if ("min_distance" in d) k.min_distance = d.min_distance;
    Object.assign(k.footprints, d.footprints || {});
  }
  for (const [q, v] of Object.entries(e.quotas || {})) { const x = S.work.quotas.find(y => y.key === q); if (x) x.limit = v; }
  for (const [id, d] of Object.entries(e.slots || {})) {
    const s = S.work.slots.find(x => String(x.id) === id); if (s) Object.assign(s.allow, d.allow || {});
  }
}
async function doCheck() {
  try {
    const r = await api("/api/check", { chapter: S.chapter.key, edits: edits() });
    status(r.changes.length ? `Looks good: ${r.changes.length} change(s) cook cleanly` : "Valid, but nothing changed", "ok");
  } catch (err) { status(err.message, "bad"); }
}
async function doSave() {
  const id = $("modid").value.trim().toLowerCase();
  if (!id) { status("Give the mod an id first (letters, digits, - or _).", "bad"); $("modid").focus(); return; }
  try {
    const r = await api("/api/save", { chapter: S.chapter.key, mod_id: id, name: $("modname").value.trim(), edits: edits() });
    S.lastSave = r; status(`Saved ${r.path}`, "ok");
    if (![...$("openmod").options].some(o => o.value === id)) {
      $("openmod").insertAdjacentHTML("beforeend", `<option value="${esc(id)}">${esc(id)} (${esc(S.chapter.key)})</option>`);
    }
    render();
  } catch (err) { status(err.message, "bad"); }
}
async function init() {
  // Mod id / name live outside the panel so switching tabs keeps them.
  document.body.insertAdjacentHTML("beforeend", `<input id="modid-keep" type="hidden"><input id="modname-keep" type="hidden">`);
  let gl = false;
  try { gl = glInit(); } catch (err) { console.error(err); }
  if (!gl) { $("v3d").disabled = true; $("v3d").title = "This browser has no WebGL2"; }
  const st = await api("/api/state");
  S.chapters = st.chapters;
  $("chapter").innerHTML = st.chapters.map(c => `<option value="${esc(c.key)}">${esc(c.label)}</option>`).join("");
  $("openmod").innerHTML = `<option value="">—</option>` + st.mods.map(m => `<option value="${esc(m.id)}">${esc(m.id)} (${esc(m.chapter)})</option>`).join("");
  if (!st.chapters.length) { status("No tile-generated chapters found.", "bad"); return; }
  const hash = new URLSearchParams(location.hash.slice(1));
  setView(hash.get("view") || store.get("rsmm.mapeditor.view") || "3d");
  const want = st.chapters.find(c => c.key === hash.get("chapter")) || st.chapters[0];
  await loadChapter(want.key);
  const ki = S.work.kinds.findIndex(k => k.name === hash.get("kind"));
  if (ki >= 0) S.kind = ki;
  const sc = Number(hash.get("scenario"));
  if (Number.isInteger(sc) && sc >= 0 && sc < S.work.scenarios.length) { S.scen = sc; $("scenario").value = String(sc); }
  render();
}
$("chapter").addEventListener("change", async e => {
  if (changeList().length && !confirm("Discard unsaved changes?")) { e.target.value = S.chapter.key; return; }
  try { await loadChapter(e.target.value); } catch (err) { status(err.message, "bad"); }
});
$("openmod").addEventListener("change", async e => {
  const id = e.target.value; if (!id) return;
  if (changeList().length && !confirm("Discard unsaved changes?")) { e.target.value = ""; return; }
  try {
    const m = await api("/api/mod?id=" + encodeURIComponent(id));
    $("modid-keep").value = id; $("modname-keep").value = m.name || "";
    await loadChapter(m.chapter, m.edits); setTab("changes"); render();
    status(`Opened ${id}: ${changeList().length} change(s)`, "ok");
  } catch (err) { status(err.message, "bad"); }
});
$("scenario").addEventListener("change", e => { S.scen = Number(e.target.value); render(); });
$("v3d").addEventListener("click", () => { setView("3d"); render(); });
$("v2d").addEventListener("click", () => { setView("2d"); render(); });
$("recenter").addEventListener("click", resetCamera);
$("models").addEventListener("change", e => {
  S.models = e.target.checked; G.dirty = true;
  if (S.models && G.three && !G.three.groups.scenery.children.length && S.chapter) loadScenery(S.chapter.key);
  render();
});
$("spots").addEventListener("change", e => { S.showSpots = e.target.checked; render(); });
$("sample").addEventListener("click", () => {
  if (!S.pool.length) { status("This chapter's tile pool isn't loaded yet.", "bad"); return; }
  S.seed = (S.seed * 1103515245 + 12345) >>> 0 || 1;
  S.layout = sampleLayout(S.seed); S.layoutSample = true;
  if (!S.models) { S.models = true; $("models").checked = true; }
  status(`Sample layout: ${Object.keys(S.layout).length} tiles placed (click again for another)`, "ok");
  drawLayout(); setView(S.view); render();
});
$("clearlayout").addEventListener("click", () => { S.layout = {}; S.layoutSample = false; drawLayout(); setView(S.view); render(); });
$("showall").addEventListener("change", e => { S.showAll = e.target.checked; render(); });
document.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", () => { setTab(b.dataset.tab); render(); }));
window.addEventListener("beforeunload", e => { if (S.work && changeList().length && !S.lastSave) { e.preventDefault(); e.returnValue = ""; } });
Object.assign(window, { rsmmEditor: { S, G, project, pickAt } });   // for tests and the console
init().catch(err => status(err.message, "bad"));
</script>
</body>
</html>
"""
