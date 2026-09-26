# ruff: noqa: E501  (the string below is HTML/JS, not Python)
"""The ability editor's single page: HTML, CSS and JS, no build step, no assets.

A Python module (not a data file) so the frozen CLI bundles it through
``--collect-submodules=rsmm.cli`` with no build-script change, like the map
editor's page. Nothing game-derived is embedded: every part, field and link
comes from ``/api/graph``, which reads the user's own install at request time.

Written for people new to modding. The page opens on **Numbers**: every
literal the chosen ability uses, as a plain form (type a value, press Enter),
named after its part with the ability's own name stripped off. The graph of
parts and links is the second tab, **Diagram**, for re-pointing links and
copying abilities. Changes sit in a bar along the bottom with the build status
and a Copy button; changing the same field twice replaces the earlier change,
and putting a value back removes it.

``__RSMM_TOKEN__`` is replaced per launch; every POST must echo it.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ability Editor</title>
<style>
:root {
  --bg: #f4f3ef; --panel: #fff; --ink: #1d1d1f; --muted: #6a6a70; --line: #deddd8;
  --accent: #6d35e8; --accentbg: #efe8fd; --ok: #1f8a4c; --okbg: #e3f5ea; --bad: #b8322a; --badbg: #fbe7e5;
  --warn: #9a6200; --warnbg: #fff3d6; --chip: #efeee9; --node: #fff; --ext: #ecebe6; --edge: #9b9aa0;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #151517; --panel: #1f1f22; --ink: #ececef; --muted: #a0a0a8; --line: #34343a; --accentbg: #2a2140;
          --chip: #2a2a2f; --node: #26262b; --ext: #1b1b1e; --edge: #6d6d75;
          --okbg: #13301f; --badbg: #3a1614; --warnbg: #33270c; }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; font: 14px/1.45 system-ui, sans-serif; background: var(--bg); color: var(--ink);
       display: grid; grid-template: "top top" auto "left main" 1fr "left bar" auto / 240px 1fr; height: 100vh; }
header { grid-area: top; display: flex; flex-wrap: wrap; gap: 12px; align-items: center; padding: 8px 14px; border-bottom: 1px solid var(--line); background: var(--panel); }
header h1 { font-size: 16px; margin: 0 8px 0 0; }
select, input, button, textarea { font: inherit; color: inherit; background: var(--panel); border: 1px solid var(--line); border-radius: 7px; padding: 5px 9px; }
button { cursor: pointer; } button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
button:disabled { opacity: .45; cursor: default; }
button.small { padding: 1px 8px; font-size: 12px; }
button.link { border: none; background: none; color: var(--accent); padding: 0; text-decoration: underline; }
.muted { color: var(--muted); } .tiny { font-size: 12px; }
code { background: var(--chip); border-radius: 4px; padding: 0 4px; }
#left { grid-area: left; overflow: auto; border-right: 1px solid var(--line); background: var(--panel); padding: 10px; }
#left h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 12px 4px 4px; }
#left input[type=search] { width: 100%; }
.grp { display: flex; justify-content: space-between; gap: 6px; padding: 5px 8px; border-radius: 7px; cursor: pointer; }
.grp:hover { background: var(--chip); } .grp.on { background: var(--accent); color: #fff; }
.grp span { opacity: .7; font-size: 12px; }
#main { grid-area: main; display: grid; grid-template-rows: auto 1fr; min-height: 0; min-width: 0; }
#tabs { display: flex; align-items: center; gap: 4px; padding: 8px 14px 0; border-bottom: 1px solid var(--line); }
#tabs h2 { font-size: 17px; margin: 0 16px 6px 0; }
.tab { border: none; border-bottom: 3px solid transparent; border-radius: 0; background: none; padding: 6px 12px; color: var(--muted); }
.tab.on { border-bottom-color: var(--accent); color: var(--ink); font-weight: 600; }
.pane { min-height: 0; overflow: auto; }
#numbers { padding: 14px 18px 30px; }
#numbers .wrap { max-width: 860px; }
.help { background: var(--accentbg); border-radius: 10px; padding: 10px 14px; margin-bottom: 14px; }
.help ol { margin: 6px 0; padding-left: 20px; }
.sect { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 18px 0 6px; }
.num { display: grid; grid-template-columns: 1fr 150px 70px; gap: 10px; align-items: center; padding: 8px 10px; border-radius: 8px; border: 1px solid transparent; }
.num:nth-child(odd) { background: var(--panel); }
.num.changed { border-color: var(--accent); background: var(--accentbg); }
.num .lbl { font-weight: 600; } .num .sub { color: var(--muted); font-size: 12px; }
.num input, .num select { width: 100%; }
.num input.bad { border-color: var(--bad); }
.num .was { font-size: 12px; color: var(--muted); }
.dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 5px; vertical-align: middle; }
.card { border: 1px solid var(--line); border-radius: 10px; padding: 12px; margin-top: 18px; background: var(--panel); }
.card .row { display: flex; gap: 6px; margin-top: 8px; }
#diagram { display: grid; grid-template-columns: 1fr 360px; overflow: hidden; }
#mid { position: relative; overflow: hidden; }
#mid svg { width: 100%; height: 100%; cursor: grab; display: block; }
#nav { position: absolute; right: 12px; top: 12px; display: grid; grid-template-columns: repeat(3, 38px); gap: 4px; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 6px; }
#nav button { padding: 4px 0; font-size: 16px; }
#legend { position: absolute; left: 12px; bottom: 10px; display: flex; flex-wrap: wrap; gap: 6px; max-width: 70%; }
.lg { display: flex; align-items: center; gap: 4px; font-size: 12px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 1px 8px; }
#right { overflow: auto; border-left: 1px solid var(--line); background: var(--panel); padding: 12px; }
#right h2 { font-size: 16px; margin: 0 0 4px; }
.badge { display: inline-block; color: #fff; border-radius: 10px; padding: 0 8px; font-size: 12px; margin-right: 6px; }
.explain { background: var(--chip); border-radius: 8px; padding: 6px 9px; margin: 6px 0 10px; font-size: 13px; }
.f { border-top: 1px solid var(--line); padding: 8px 0; }
.f .n { font-weight: 600; } .f .h { color: var(--muted); font-size: 12px; }
.f .t { word-break: break-word; margin: 3px 0 6px; font-size: 13px; }
.f .row { display: flex; flex-wrap: wrap; gap: 6px; } .f .row > :first-child { flex: 1; min-width: 0; }
.item { display: flex; justify-content: space-between; align-items: center; gap: 6px; font-size: 13px; padding: 2px 0; }
details { margin-top: 8px; } summary { cursor: pointer; color: var(--muted); }
#bar { grid-area: bar; border-top: 1px solid var(--line); background: var(--panel); padding: 8px 14px; max-height: 45vh; overflow: auto; }
#bar .head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
#status { border-radius: 8px; padding: 4px 10px; font-size: 13px; flex: 1; min-width: 240px; white-space: pre-wrap; }
#status.ok { background: var(--okbg); color: var(--ok); } #status.bad { background: var(--badbg); color: var(--bad); }
#status.warn { background: var(--warnbg); color: var(--warn); } #status.idle { background: var(--chip); color: var(--muted); }
#list { margin: 8px 0 4px; padding-left: 22px; } #list li { margin: 3px 0; } #list li.bad { color: var(--bad); font-weight: 600; }
#problems { color: var(--bad); margin: 0 0 8px; padding-left: 22px; } #problems:empty { display: none; }
#toml { width: 100%; min-height: 90px; font: 12px ui-monospace, monospace; resize: vertical; margin-top: 6px; }
g.node rect.box { fill: var(--node); stroke: var(--line); } g.node.ext rect.box { fill: var(--ext); stroke-dasharray: 4 3; }
g.node.sel rect.box { stroke: var(--accent); stroke-width: 3; } g.node.hit rect.box { stroke: var(--warn); stroke-width: 3; }
g.node text { fill: var(--ink); font-size: 12px; } g.node .c { fill: var(--muted); font-size: 10.5px; } g.node { cursor: pointer; }
path.e { fill: none; stroke: var(--edge); stroke-width: 1.2; opacity: .75; } path.e.hi { stroke: var(--accent); stroke-width: 2.2; opacity: 1; }
text.el { fill: var(--muted); font-size: 11px; } text.el.hi { fill: var(--accent); font-weight: 600; }
</style>
</head>
<body>
<header>
  <h1>Ability Editor</h1>
  <label>Hero <select id="hero" title="The shipped hero whose abilities you are looking at. Your custom hero uses this one as its base."></select></label>
  <label class="tiny muted">File <select id="entity" title="A hero is several files. Almost everything lives in the main one; FX is visual effects, the rest are pets, projectiles and skins."></select></label>
  <input id="find" type="search" placeholder="Find a part by name…" style="min-width:220px" title="Type part of a name, then Enter to jump to it">
  <button id="helpBtn" class="small">How does this work?</button>
  <span id="busy" class="muted tiny"></span>
</header>
<nav id="left">
  <input id="filter" type="search" placeholder="Filter abilities">
  <div id="groups"></div>
  <label class="tiny muted" style="display:block;margin:12px 4px"><input type="checkbox" id="showAll"> also show movement, animation and other groups</label>
</nav>
<main id="main">
  <div id="tabs">
    <h2 id="groupTitle"></h2>
    <button class="tab on" data-tab="numbers" title="Change the numbers this ability uses">Numbers</button>
    <button class="tab" data-tab="diagram" title="See how the parts connect, re-point links, copy the ability">Diagram (advanced)</button>
  </div>
  <section id="numbers" class="pane"><div class="wrap">
    <div id="help" class="help">
      <b>How this works.</b>
      <ol>
        <li>Pick an ability on the left.</li>
        <li>Type a new number in the box and press <b>Enter</b>. The row turns purple and the change is checked straight away. <b>↺</b> puts the original back.</li>
        <li>When the bar at the bottom says <b>Ready to build</b>, press <b>Copy manifest code</b>, paste it into your custom hero's <code>manifest.toml</code>, and run <code>rsmm apply</code>.</li>
      </ol>
      Nothing here touches your game until you apply. To change <i>what triggers what</i>, use the <b>Diagram</b> tab.
      <div style="margin-top:6px"><button class="small" id="helpOk">Got it, hide this</button></div>
    </div>
    <div id="numList"></div>
  </div></section>
  <section id="diagram" class="pane" hidden>
    <div id="mid">
      <svg id="svg"><g id="view"></g></svg>
      <div id="nav" title="Move and zoom the picture (keys: arrows, + and -, 0 to fit)">
        <span></span><button id="up" title="Move up (↑)">↑</button><span></span>
        <button id="left_" title="Move left (←)">←</button><button id="fit" title="Fit to screen (0)">⤢</button><button id="right_" title="Move right (→)">→</button>
        <span></span><button id="down" title="Move down (↓)">↓</button><span></span>
        <button id="zin" title="Zoom in (+)">+</button><span class="tiny muted" id="zoom" style="text-align:center;align-self:center">100%</span><button id="zout" title="Zoom out (−)">−</button>
      </div>
      <div id="legend"></div>
    </div>
    <aside id="right"></aside>
  </section>
</main>
<section id="bar">
  <div class="head">
    <div id="status" class="idle">No changes yet.</div>
    <button id="copy" class="primary" title="Copy your changes as manifest code" disabled>Copy manifest code</button>
    <button id="toggleList" class="small">Show changes</button>
    <button id="undo" class="small" title="Remove the last change">Undo last</button>
    <button id="clear" class="small" title="Remove every change">Start over</button>
  </div>
  <div id="details" hidden>
    <ol id="list"></ol>
    <ul id="problems" class="tiny"></ul>
    <div class="tiny muted">Paste the code under your hero's <code>[[content]]</code> block (<code>kind = "hero"</code>, <code>base = "<span id="baseName"></span>"</code>) in <code>manifest.toml</code>, then run <code>rsmm apply</code>.</div>
    <textarea id="toml" readonly></textarea>
  </div>
</section>
<script>
const TOKEN = "__RSMM_TOKEN__";
const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, ...kids) => {
  const e = ["svg","g","rect","text","path","defs","marker","title","circle"].includes(tag) ? document.createElementNS(SVGNS, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "text") e.textContent = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const k of kids) if (k !== null && k !== undefined && k !== false) e.append(k);
  return e;
};

// Plain-language names for part types (by class) and fields (by name).
const TYPES = {
  State: ["Phase", "#6d35e8", "A phase the hero or ability can be in. While it is active it switches other parts on; events are phases that last an instant."],
  Timer: ["Timer", "#d9822b", "Waits a while, then does something (once or several times)."],
  Value: ["Number", "#1f8a8a", "A number (or yes/no) other parts read: a damage, a duration, a count."],
  ValueSelector: ["Number by rarity", "#1f8a8a", "A number that changes with the talent's rarity or another setting."],
  ValueOperations: ["Math", "#2f8fb0", "Adds or multiplies numbers together."],
  ValueOperation: ["Math", "#2f8fb0", "Combines two numbers."],
  Tester: ["Check", "#c0392b", "An if/else: when its condition is true it runs one part, otherwise another."],
  EntitySpawner: ["Spawner", "#7c9a2f", "Creates something in the world: a projectile, a zone, a pet."],
  SpawnerValue: ["Spawn setting", "#7c9a2f", "Passes a number to the thing a spawner creates."],
  ZoneAttack: ["Area attack", "#b54a8c", "Hits everything inside an area."],
  Damage: ["Damage", "#b54a8c", "How much damage a hit does and of what kind."],
  Modifier: ["Buff / debuff", "#8a6fd1", "Changes a stat for a while (shield, burn, speed…)."],
  NamedEventSender: ["Send signal", "#4f86c6", "Broadcasts a named game event other parts can listen to."],
  NamedEventListener: ["Receive signal", "#4f86c6", "Waits for a named game event, then starts a phase."],
  Fx: ["Visual effect", "#e0a100", "Plays a particle effect."],
  FModEvent: ["Sound", "#999", "Plays a sound."],
  Animatic: ["Animation", "#aa7744", "Plays an animation on the hero."],
  AnimClip: ["Animation clip", "#aa7744", "An animation file the hero can play."],
  TwoSpeedAnimatic: ["Animation", "#aa7744", "Plays an animation at one of two speeds."],
  GetValue: ["Read number", "#1f8a8a", "Reads a number from another entity."],
  SmoothValue: ["Smooth number", "#1f8a8a", "Moves a number gradually toward a target."],
  RangedRandom: ["Random number", "#1f8a8a", "Picks a random number between two limits."],
  Selector: ["Chooser", "#666", "Picks one of several parts."],
  SkillController: ["Talent", "#6d35e8", "Controls one talent (its rarity and whether the hero has it)."],
  AbilityController: ["Ability slot", "#6d35e8", "Controls one ability slot: cooldown and activation."],
  Counter: ["Counter", "#2f8fb0", "Counts up and down."],
  StringFormatValue: ["Card text", "#999", "Text shown on a talent card, with numbers filled in."],
  "3dGraphicObject": ["3D model", "#777", "A mesh shown in the world."],
  "3dNode": ["Position", "#777", "A point attached to the hero (hand, head…)."],
};
const FIELDS = {
  duration: "How long it lasts, or how long a timer waits (seconds).",
  count: "How many times the timer fires.",
  "bias?": "An extra delay or offset (meaning not certain).",
  on_tick: "What the timer starts every time it fires.",
  on_end: "What the timer starts when it is done.",
  state: "The phase this runs in: it only works while that phase is active.",
  "paused?": "When yes, the timer is paused (meaning not certain).",
  activates: "What this phase switches on when it starts.",
  while_active: "What stays on only while this phase is active.",
  "on_enter?": "What starts when this phase begins (meaning not certain).",
  "on_exit?": "What starts when this phase ends (meaning not certain).",
  "deactivates?": "What this phase switches off (meaning not certain).",
  "disables_while_active?": "What is switched off while this phase is active (meaning not certain).",
  value: "The number itself.",
  on_true: "What runs when the check is true.",
  on_false: "What runs when the check is false.",
  test: "The condition that is checked.",
  template: "What gets created (a projectile, zone or pet file).",
  position: "Where it is created.",
  "speed?": "How fast it moves (meaning not certain).",
  event: "The name of the signal.",
  on_event: "What starts when the signal arrives.",
  payload: "A number sent along with the signal.",
  min: "Lowest possible number.", max: "Highest possible number.",
  amount: "How strong the change is.",
  default: "The number used when no other entry applies.",
  entries: "One number per case (e.g. per rarity).",
  a: "First number.", b: "Second number.",
};
// Unknown or raw-code fields; `op?` is an operator ENUM (1, 3…), not a number to tune.
const ADVANCED = /^(flag|_|mode$|mode_|ref_|value_|bytes_|list_|obj_|epsilon|int_mode|op_type|flag_|op\?$)/;
const typeOf = (cls) => TYPES[cls] || [cls.replace(/([a-z])([A-Z])/g, "$1 $2"), "#888", "A part of type " + cls + "."];
const niceField = (n) => n.replace(/\?$/, "").replace(/_/g, " ");

let S = { hero: "", entity: "", steps: [], data: null, group: "", sel: null, tab: "numbers",
          tf: { x: 40, y: 40, k: 1 }, bounds: null, flash: null };

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-RSMM-Token": TOKEN }, body: JSON.stringify(body) });
  const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j;
}
async function refresh() {
  $("busy").textContent = "checking…";
  try { S.data = await post("/api/graph", { hero: S.hero, entity: S.entity, steps: S.steps }); S.entity = S.data.entity; }
  catch (e) { setStatus("bad", e.message); $("busy").textContent = ""; return; }
  $("busy").textContent = "";
  $("baseName").textContent = S.hero;
  const main = "Hero_" + S.hero;
  $("entity").replaceChildren(...S.data.entities.map(n => el("option", { value: n,
    text: n === main ? "Main (abilities)" : n.startsWith(main + "_") ? n.slice(main.length + 1).replace(/_/g, " ") : n })));
  $("entity").value = S.entity;
  const gs = [...groupsOf().keys()];
  const keep = S.group && gs.includes(S.group);
  if (!keep) S.group = gs.find(g => g === "Ability Primary") || gs.find(g => g.startsWith("Ability")) || gs[0] || "";
  drawGroups(); drawSteps(); drawNumbers();
  if (S.tab === "diagram") { drawGraph(!keep); inspect(S.sel && byId(S.sel.id) ? S.sel.id : null); drawLegend(); }
}
const byId = (id) => S.data.components.find(c => c.id === id);
const groupsOf = () => { const m = new Map(); for (const c of S.data.components) m.set(c.group, (m.get(c.group) || 0) + 1); return new Map([...m].sort()); };
const kindOfGroup = (g) => g.startsWith("Ability") ? "Abilities" : g.startsWith("Skill") ? "Talents" : "Other";
function selectGroup(g) {
  S.group = g; S.sel = null; drawGroups(); drawNumbers();
  if (S.tab === "diagram") { drawGraph(true); inspect(null); drawLegend(); }
}

// A part's name without the words it shares with its ability: in "Ability
// Primary", "Primary Ability Shots Delay" reads as "Shots Delay".
function short(name, group) {
  const drop = new Set((group || "").toLowerCase().split(/\s+/));
  const w = name.split(/\s+/); let i = 0;
  while (i < w.length - 1 && drop.has(w[i].toLowerCase())) i++;
  return w.slice(i).join(" ");
}

function drawGroups() {
  const f = $("filter").value.toLowerCase(), all = $("showAll").checked, out = [];
  for (const sect of ["Abilities", "Talents", "Other"]) {
    if (sect === "Other" && !all) continue;
    const rows = [...groupsOf()].filter(([g]) => kindOfGroup(g) === sect && g.toLowerCase().includes(f));
    if (!rows.length) continue;
    out.push(el("h3", { text: sect }));
    for (const [g, n] of rows) out.push(el("div", { class: "grp" + (g === S.group ? " on" : ""), title: `${n} parts`,
      onclick: () => selectGroup(g) }, el("div", { text: g || "(no group)" }), el("span", { text: n })));
  }
  $("groups").replaceChildren(...out);
  $("groupTitle").textContent = S.group || "Pick an ability";
}

// ---- the Numbers tab ------------------------------------------------------------
function literal(f, text) {
  text = text === undefined ? f.text : text;
  if (["bool", "u32", "f32"].includes(f.kind)) return f.kind === "bool" ? { value: text === "True" ? "yes" : "no", bool: true, parse: yesNo } : { value: text, parse: num };
  if (f.kind !== "value" || f.targets.length) return null;
  const m = text.match(/^(f32|int|bool|vec2|vec3|vec4) (.*)$/); if (!m) return null;
  if (m[1] === "bool") return { value: m[2] === "True" ? "yes" : "no", bool: true, parse: yesNo };
  if (m[1].startsWith("vec")) return { value: m[2].split(" ").join(", "), parse: (s) => { const v = s.split(/[ ,]+/).filter(Boolean).map(Number); return v.length && v.every(Number.isFinite) ? v : undefined; } };
  return { value: m[2], parse: m[1] === "int" ? (s) => { const n = num(s); return Number.isInteger(n) ? n : undefined; } : num };
}
const num = (s) => { const n = Number(String(s).trim()); return String(s).trim() !== "" && Number.isFinite(n) ? n : undefined; };
const yesNo = (s) => { s = String(s).trim().toLowerCase(); return ["yes", "true", "1", "on"].includes(s) ? true : ["no", "false", "0", "off"].includes(s) ? false : undefined; };

// Parts that READ this one; a phase switching it on (a ref[] list) is not a use.
function usedBy(id) {
  const out = [];
  for (const c of S.data.components) for (const f of c.fields)
    if (f.kind !== "ref[]" && f.targets.includes(id)) out.push(short(c.name, c.group) + (f.name === "value" ? "" : " (" + niceField(f.name) + ")"));
  return [...new Set(out)];
}
function numberRow(c, f) {
  const lit = literal(f), addr = `${c.name}.${f.name}`, step = findStep("set", addr);
  const name = short(c.name, S.group), [tlabel, color] = typeOf(c.cls);
  const label = (c.cls === "Value" && f.name === "value") ? name : `${name} · ${niceField(f.name)}`;
  const users = usedBy(c.id), help = FIELDS[f.name] && f.name !== "value" ? FIELDS[f.name] : "";
  const commit = (raw) => {
    const v = lit.parse(raw);
    if (v === undefined) { inp.classList.add("bad"); inp.title = lit.bool ? "yes or no" : "a number"; return; }
    inp.classList.remove("bad");
    const orig = f.was !== null ? literal(f, f.was) : lit;
    if (JSON.stringify(v) === JSON.stringify(orig.parse(orig.value))) { if (step) removeStep(step); return; }
    if (JSON.stringify(v) !== JSON.stringify(lit.parse(lit.value))) setStep({ set: addr, value: v });
  };
  // Show the user's own value even when the build failed (the server then
  // draws the unedited graph, which would silently undo their typing).
  const shown = step ? (step.value === true ? "yes" : step.value === false ? "no" : [].concat(step.value).join(", ")) : lit.value;
  const inp = lit.bool
    ? el("select", { onchange: (e) => commit(e.target.value) }, el("option", { value: "yes", text: "yes" }), el("option", { value: "no", text: "no" }))
    : el("input", { value: shown, inputmode: "decimal", onchange: (e) => commit(e.target.value),
                    onkeydown: (e) => { if (e.key === "Escape") { e.target.value = shown; e.target.classList.remove("bad"); } } });
  if (lit.bool) inp.value = shown;
  const wasLit = f.was !== null ? literal(f, f.was) : null;
  return el("div", { class: "num" + (step ? " changed" : ""), title: c.name },
    el("div", {},
      el("div", { class: "lbl", text: label }),
      el("div", { class: "sub" }, el("span", { class: "dot", style: `background:${color}` }), tlabel,
        help ? " · " + help : "", users.length ? " · used by " + users.slice(0, 3).join(", ") + (users.length > 3 ? ` +${users.length - 3}` : "") : "")),
    inp,
    el("div", {}, step ? el("button", { class: "small", title: "Put the original value back", text: "↺ reset", onclick: () => removeStep(step) }) : null,
      wasLit ? el("div", { class: "was", text: "was " + wasLit.value }) : null));
}
function drawNumbers() {
  const parts = S.data.components.filter(c => c.group === S.group);
  const main = [], tech = [];
  for (const c of parts) for (const f of c.fields) {
    if (!literal(f)) continue;
    (ADVANCED.test(f.name) ? tech : main).push([c, f]);
  }
  // Plain numbers first (what a beginner is looking for), yes/no last.
  const rank = ([c, f]) => (c.cls === "Value" ? 0 : 1) + (literal(f).bool ? 2 : 0);
  main.sort((a, b) => rank(a) - rank(b) || short(a[0].name, S.group).localeCompare(short(b[0].name, S.group)));
  const out = [];
  if (!main.length) out.push(el("div", { class: "muted", text: "This ability has no plain numbers to change. Its parts only link to each other: use the Diagram tab." }));
  else out.push(el("div", { class: "sect", text: `Numbers in ${S.group} (${main.length})` }), el("div", {}, ...main.map(([c, f]) => numberRow(c, f))));
  if (tech.length) out.push(el("details", {}, el("summary", { text: `Technical settings (${tech.length}): internal flags whose meaning is not known yet` }),
    el("div", {}, ...tech.map(([c, f]) => numberRow(c, f)))));
  out.push(el("div", { class: "card" },
    el("b", { text: "Make a copy of this ability" }),
    el("div", { class: "tiny muted", text: "The copy gets its own parts (their names end with the new name). It does nothing until something links to it: afterwards, use the Diagram tab to point one of your parts at it." }),
    el("div", { class: "row" }, el("input", { id: "cloneAs", placeholder: "New name, e.g. Echo", style: "flex:1" }),
      el("button", { class: "primary", text: "Copy ability", onclick: () => { const as = $("cloneAs").value.trim(); if (as) addStep({ clone: S.group, as }); else $("cloneAs").focus(); } }))));
  $("numList").replaceChildren(...out);
}

// ---- the Diagram tab --------------------------------------------------------------
function drawGraph(fitAfter) {
  const view = $("view"); view.replaceChildren();
  const inGroup = S.data.components.filter(c => c.group === S.group);
  const ids = new Set(inGroup.map(c => c.id));
  const edges = [], ext = new Map();
  for (const c of inGroup) for (const f of c.fields) f.targets.forEach((t, i) => {
    edges.push({ from: c.id, to: t, label: niceField(f.name) });
    if (!ids.has(t)) ext.set(t, byId(t) || outside(t, f.paths[i]));
  });
  const nodes = [...inGroup, ...ext.values()], depth = new Map(nodes.map(n => [n.id, 0]));
  for (let i = 0; i < Math.min(nodes.length, 30); i++) for (const e of edges)
    if (e.from !== e.to && depth.get(e.to) < depth.get(e.from) + 1 && depth.get(e.from) < 10) depth.set(e.to, depth.get(e.from) + 1);
  const cols = new Map();
  for (const n of nodes) { const d = ids.has(n.id) ? depth.get(n.id) : Math.max(depth.get(n.id), 1); if (!cols.has(d)) cols.set(d, []); cols.get(d).push(n); }
  const W = 240, H = 50, pos = new Map();
  for (const [d, list] of [...cols].sort((a, b) => a[0] - b[0])) list.forEach((n, i) => pos.set(n.id, { x: d * (W + 100), y: i * (H + 24) }));
  let maxX = 0, maxY = 0;
  for (const p of pos.values()) { maxX = Math.max(maxX, p.x + W); maxY = Math.max(maxY, p.y + H); }
  S.bounds = { w: maxX, h: maxY };
  const stack = {};
  for (const e of edges) {
    const a = pos.get(e.from), b = pos.get(e.to); if (!a || !b) continue;
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
    const d = e.from === e.to ? `M${x1},${y1} C${x1 + 50},${y1 - 50} ${x1 - 50},${y1 - 50} ${x1 - 20},${a.y}` : `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
    // Only the selected part's links are labelled (and drawn strong): labels
    // on every arrow pile up where many links leave one part.
    const hi = S.sel && (e.from === S.sel.id || e.to === S.sel.id);
    view.append(el("path", { class: "e" + (hi ? " hi" : ""), d, "marker-end": "url(#arrow)" }, el("title", { text: e.label })));
    if (hi) {
      const out = e.from === S.sel.id, key = out ? "o" + e.from : "i" + e.to;
      const nth = stack[key] = (stack[key] || 0) + 1;       // stack labels leaving/entering one point
      view.append(el("text", { class: "el hi", x: out ? x1 + 8 : x2 - 8 - e.label.length * 6, y: (out ? y1 : y2) - 5 - (nth - 1) * 12, text: e.label }));
    }
  }
  for (const n of nodes) {
    const p = pos.get(n.id), isExt = !ids.has(n.id), [label, color] = n.cls ? typeOf(n.cls) : ["", "#aaa"];
    const g = el("g", { class: "node" + (isExt ? " ext" : "") + (S.sel && S.sel.id === n.id ? " sel" : "") + (S.flash === n.id ? " hit" : ""), transform: `translate(${p.x},${p.y})`,
      onclick: (ev) => { ev.stopPropagation(); if (isExt && byId(n.id)) { S.group = n.group; drawGroups(); drawNumbers(); drawGraph(true); drawLegend(); } inspect(n.id); } },
      el("title", { text: isExt ? (n.shared ? `${n.name}: a part of ${n.shared}, shared by many heroes. It can be linked to but not changed here.` : `${n.name} (in the group "${n.group}"; click to go there)`) : `${n.name}\n${label}: ${typeOf(n.cls)[2]}` }),
      el("rect", { class: "box", width: W, height: H, rx: 9 }),
      el("rect", { width: 6, height: H, rx: 3, fill: color }),
      el("text", { x: 14, y: 20, text: trim(isExt ? n.name : short(n.name, S.group), 32) }),
      el("text", { class: "c", x: 14, y: 38, text: isExt ? (n.shared ? "shared: " + trim(n.shared, 26) : "→ in " + trim(n.group || "?", 26)) : label }));
    view.append(g);
  }
  if (fitAfter) fit(); else applyTf();
}
const trim = (s, n) => s.length > n ? s.slice(0, n - 1) + "…" : s;
function drawLegend() {
  const seen = [...new Set(S.data.components.filter(c => c.group === S.group).map(c => c.cls))].slice(0, 10);
  $("legend").replaceChildren(...seen.map(c => { const [l, col, h] = typeOf(c); return el("span", { class: "lg", title: h }, el("span", { class: "dot", style: `background:${col};margin:0` }), l); }));
}

// view controls: buttons and keys (a scroll wheel is optional)
function applyTf() { $("view").setAttribute("transform", `translate(${S.tf.x},${S.tf.y}) scale(${S.tf.k})`); $("zoom").textContent = Math.round(S.tf.k * 100) + "%"; }
function zoomBy(f, cx, cy) {
  const r = $("svg").getBoundingClientRect(); if (cx === undefined) cx = r.width / 2; if (cy === undefined) cy = r.height / 2;
  const k = Math.min(3, Math.max(0.15, S.tf.k * f));
  S.tf.x = cx - (cx - S.tf.x) * k / S.tf.k; S.tf.y = cy - (cy - S.tf.y) * k / S.tf.k; S.tf.k = k; applyTf();
}
function pan(dx, dy) { S.tf.x += dx; S.tf.y += dy; applyTf(); }
function fit() {
  const r = $("svg").getBoundingClientRect(); if (!S.bounds || !r.width) return;
  // Never shrink below a size whose text is readable; a big ability starts at
  // its top-left corner instead, and the arrow buttons move around it.
  const k = Math.min(1.1, Math.max(0.7, Math.min((r.width - 150) / S.bounds.w, (r.height - 60) / S.bounds.h)));
  const fitsW = S.bounds.w * k <= r.width - 150, fitsH = S.bounds.h * k <= r.height - 60;
  S.tf = { k, x: fitsW ? (r.width - 130 - S.bounds.w * k) / 2 : 24, y: fitsH ? (r.height - S.bounds.h * k) / 2 : 24 }; applyTf();
}
const STEP = 120;
$("zin").onclick = () => zoomBy(1.25); $("zout").onclick = () => zoomBy(0.8); $("fit").onclick = fit;
$("up").onclick = () => pan(0, STEP); $("down").onclick = () => pan(0, -STEP);
$("left_").onclick = () => pan(STEP, 0); $("right_").onclick = () => pan(-STEP, 0);
window.addEventListener("keydown", (e) => {
  if (S.tab !== "diagram" || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  const k = { ArrowUp: () => pan(0, STEP), ArrowDown: () => pan(0, -STEP), ArrowLeft: () => pan(STEP, 0), ArrowRight: () => pan(-STEP, 0),
              "+": () => zoomBy(1.25), "=": () => zoomBy(1.25), "-": () => zoomBy(0.8), "0": fit }[e.key];
  if (k) { e.preventDefault(); k(); }
});
let drag = null;
$("svg").addEventListener("mousedown", (e) => { drag = { x: e.clientX - S.tf.x, y: e.clientY - S.tf.y }; });
window.addEventListener("mousemove", (e) => { if (drag) { S.tf.x = e.clientX - drag.x; S.tf.y = e.clientY - drag.y; applyTf(); } });
window.addEventListener("mouseup", () => drag = null);
$("svg").addEventListener("wheel", (e) => { e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.1 : 0.9, e.offsetX, e.offsetY); }, { passive: false });
window.addEventListener("resize", () => { if (S.tab === "diagram") fit(); });
$("svg").prepend(el("defs", {}, (() => { const m = el("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
  m.append(el("path", { d: "M0,0 L10,5 L0,10 z", fill: "#9b9aa0" })); return m; })()));

// the inspector (Diagram tab only)
function inspect(id) {
  const box = $("right"); box.replaceChildren();
  if (!id) {
    box.append(el("h2", { text: S.group || "Pick an ability" }),
      el("div", { class: "explain", text: "Each box is a part of the ability, each arrow a link. Click a box to see what that part does, change where its links point, or add and remove links." }),
      el("div", { class: "tiny muted", text: "Numbers are easier to change in the Numbers tab." }));
    S.sel = null; drawGraph(false); return;
  }
  const c = byId(id); S.sel = c ? { id } : null;
  if (!c) { box.append(el("div", { class: "explain", text: "That part lives in another file of the game (shared by several heroes), so it cannot be changed here." })); return; }
  const [label, color, help] = typeOf(c.cls);
  box.append(el("h2", { text: c.name }), el("div", {}, el("span", { class: "badge", style: `background:${color}`, text: label }), el("span", { class: "tiny muted", text: c.group })),
    el("div", { class: "explain", text: help }));
  const partNames = S.data.components.map(x => x.name);
  const simple = [], adv = [];
  for (const f of c.fields) (ADVANCED.test(f.name) ? adv : simple).push(fieldRow(c, f, partNames));
  box.append(...(simple.length ? simple : [el("div", { class: "tiny muted", text: "This part has no settings with a known meaning; see Technical." })]));
  if (adv.length) box.append(el("details", {}, el("summary", { text: `Technical (${adv.length} settings)` }), ...adv));
  drawGraph(false);
}
function fieldRow(c, f, partNames) {
  const row = el("div", { class: "f" }, el("div", { class: "n", text: niceField(f.name) }),
    FIELDS[f.name] ? el("div", { class: "h", text: FIELDS[f.name] }) : null);
  const addr = `${c.name}.${f.name}`, lit = literal(f);
  if (lit) {
    const inp = el("input", { value: lit.value, title: lit.bool ? "yes or no" : "a number" });
    row.append(el("div", { class: "row" }, inp, el("button", { text: "Change", onclick: () => {
      const v = lit.parse(inp.value); if (v === undefined) { inp.style.borderColor = "var(--bad)"; return; } setStep({ set: addr, value: v }); } })));
    return row;
  }
  row.append(el("div", { class: "t", text: pretty(f) }));
  if (f.kind === "ref" || (f.kind === "value" && f.targets.length))
    row.append(linkRow(partNames, (to) => setStep({ link: addr, to }), true, "Point to", currentName(f)));
  if (f.kind === "ref[]") {
    const items = f.items ? f.text.split("  |  ") : [];
    items.forEach((t, i) => row.append(el("div", { class: "item" }, el("span", { text: "• " + t.replace(/^<- /, "").split("\\").pop() }),
      el("button", { class: "small", text: "Remove", onclick: () => addStep({ remove_link: `${addr}[${i}]` }) }))));
    row.append(linkRow(partNames, (to) => addStep({ add_link: addr, to }), false, "Add"));
  }
  return row;
}
function pretty(f) {
  if (f.kind === "ref[]") return f.items ? `${f.items} link(s):` : "(nothing)";
  const t = f.text.replace(/<- \[[^\]]+\] /g, "→ ").replace(/Hero_[A-Za-z_]+\\/g, "");
  return t === "(none)" ? "(nothing)" : t;
}
function currentName(f) {
  if (!f.targets.length) return "";
  const t = byId(f.targets[0]); return t ? t.name : null;
}
function outside(id, path) {
  const m = /^\[[^\]]+\] ([^\\]+)\\(?:(.*)\\)?([^\\]+)$/.exec(path || "");
  if (!m) return { id, name: "(outside this file)", group: "", cls: "", shared: "another file" };
  return { id, name: m[3], group: m[2] || "", cls: "", shared: m[1] === "Hero_" + S.hero ? "" : m[1] };
}
function linkRow(names, act, allowNone, verb, current) {
  const inGroup = S.data.components.filter(c => c.group === S.group).map(c => c.name);
  const sel = el("select", { title: "Pick the part to link to" },
    ...(allowNone ? [el("option", { value: "", text: "(nothing)" })] : []),
    el("optgroup", { label: "In this ability" }, ...[...inGroup].sort().map(n => el("option", { value: n, text: n }))),
    el("optgroup", { label: "Everything else" }, ...names.filter(n => !inGroup.includes(n)).sort().map(n => el("option", { value: n, text: n }))));
  if (current) sel.value = current;
  const wrap = el("div", { class: "row" }, sel, el("button", { text: verb, onclick: () => {
    if (current !== undefined && sel.value === (current || "")) { sel.style.borderColor = "var(--warn)"; return; }
    act(sel.value); } }));
  if (current === null) wrap.prepend(el("div", { class: "tiny muted", style: "flex-basis:100%", text: "Now points to a shared part outside this file." }));
  return wrap;
}

// ---- changes ------------------------------------------------------------------------
const entityKey = () => (S.entity && S.entity !== "Hero_" + S.hero) ? S.entity : undefined;
const findStep = (op, addr) => S.steps.find(s => s[op] === addr && s.entity === entityKey());
function addStep(step) {
  const e = entityKey(); if (e) step.entity = e;
  S.steps.push(step); refresh();
}
// Setting a field (or pointing a link) again replaces the earlier change in
// place, so the list stays one line per thing changed.
function setStep(step) {
  const op = step.set !== undefined ? "set" : "link", old = findStep(op, step[op]);
  const e = entityKey(); if (e) step.entity = e;
  if (old) S.steps[S.steps.indexOf(old)] = step; else S.steps.push(step);
  refresh();
}
function removeStep(step) { S.steps.splice(S.steps.indexOf(step), 1); refresh(); }
function sentence(s) {
  const where = s.entity ? ` (in ${s.entity})` : "";
  const split = (a) => { const i = a.lastIndexOf("."); return [a.slice(0, i), niceField(a.slice(i + 1))]; };
  const v = (x) => x === true ? "yes" : x === false ? "no" : Array.isArray(x) ? x.join(", ") : x;
  if (s.clone) return `Copy the ability “${s.clone}” as “${s.as}”${s.from ? " from " + s.from : ""}${where}`;
  if (s.set) { const [part, fld] = split(s.set); return `${part}: set ${fld} to ${v(s.value)}${where}`; }
  if (s.link) { const [part, fld] = split(s.link); return `${part}: point ${fld} to ${s.to ? "“" + s.to + "”" : "nothing"}${where}`; }
  if (s.add_link) { const [part, fld] = split(s.add_link); return `${part}: add “${s.to}” to ${fld}${where}`; }
  if (s.remove_link) { const [part, fld] = split(s.remove_link); return `${part}: remove link ${fld}${where}`; }
  return JSON.stringify(s);
}
function setStatus(cls, text) { const st = $("status"); st.className = cls; st.textContent = text; }
function drawSteps() {
  const failing = S.data.error ? Number((/^ability step (\d+)/.exec(S.data.error) || [])[1] || 0) : 0;
  $("list").replaceChildren(...S.steps.map((s, i) => el("li", { class: i + 1 === failing ? "bad" : "" }, el("span", { text: sentence(s) + " " }),
    el("button", { class: "small", text: "Remove", onclick: () => removeStep(s) }))));
  $("toml").value = S.data.toml || "";
  $("problems").replaceChildren();
  $("copy").disabled = !S.steps.length || !!S.data.error;
  $("toggleList").textContent = ($("details").hidden ? "Show" : "Hide") + ` changes (${S.steps.length})`;
  if (!S.steps.length) setStatus("idle", "No changes yet. Type a new number in the list above and press Enter.");
  else if (S.data.error) {
    // The check lists every broken link; the bar shows the first, the panel all.
    const probs = S.data.error.replace(/^ability step \d+ \((\w+)\): /, "").split("\n").map(l => l.trim().replace(/^\[error\] /, "")).filter(Boolean);
    const lines = probs.length > 1 && probs[0].endsWith(":") ? probs.slice(1) : probs;
    setStatus("bad", `✗ This would not build: ${failing ? `change ${failing} is the problem` : "the last change is the likely cause"}. ${trim(lines[0] || "", 220)}`
      + (lines.length > 1 ? ` (+${lines.length - 1} more below)` : ""));
    $("problems").replaceChildren(...lines.map(l => el("li", { text: l })));
    $("details").hidden = false; $("toggleList").textContent = `Hide changes (${S.steps.length})`;
  }
  else if (S.data.warnings.length) setStatus("warn", `✓ Ready to build (${S.steps.length} change${S.steps.length > 1 ? "s" : ""}), with notes: ` + S.data.warnings.map(w => w.replace(/^[^:]+: \[warning\] /, "")).join("; "));
  else setStatus("ok", `✓ Ready to build: ${S.steps.length} change${S.steps.length > 1 ? "s" : ""}.`);
}

// ---- tabs, find, pickers, buttons ---------------------------------------------------
function showTab(t) {
  S.tab = t;
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("on", b.dataset.tab === t);
  $("numbers").hidden = t !== "numbers"; $("diagram").hidden = t !== "diagram";
  if (t === "diagram") { drawGraph(true); inspect(S.sel && byId(S.sel.id) ? S.sel.id : null); drawLegend(); }
}
for (const b of document.querySelectorAll(".tab")) b.onclick = () => showTab(b.dataset.tab);
$("find").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const q = $("find").value.trim().toLowerCase(); if (!q) return;
  const hit = S.data.components.find(c => c.name.toLowerCase() === q) || S.data.components.find(c => c.name.toLowerCase().includes(q));
  if (!hit) { $("find").style.borderColor = "var(--bad)"; return; }
  $("find").style.borderColor = "";
  if (kindOfGroup(hit.group) === "Other") $("showAll").checked = true;
  S.group = hit.group; S.flash = hit.id; S.sel = { id: hit.id }; drawGroups(); drawNumbers(); showTab("diagram");
});
$("filter").addEventListener("input", drawGroups);
$("showAll").addEventListener("change", drawGroups);
$("hero").addEventListener("change", () => {
  if (S.steps.length && !confirm("Switching hero clears your changes. Continue?")) { $("hero").value = S.hero; return; }
  S.hero = $("hero").value; S.entity = ""; S.steps = []; S.group = ""; S.sel = null; refresh();
});
$("entity").addEventListener("change", () => { S.entity = $("entity").value; S.group = ""; S.sel = null; refresh(); });
$("undo").addEventListener("click", () => { if (S.steps.length) { S.steps.pop(); refresh(); } });
$("clear").addEventListener("click", () => { if (S.steps.length && confirm("Remove all your changes?")) { S.steps = []; refresh(); } });
$("toggleList").addEventListener("click", () => { $("details").hidden = !$("details").hidden; drawSteps(); });
$("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("toml").value); $("copy").textContent = "Copied!"; }
  catch (e) { $("details").hidden = false; drawSteps(); $("toml").select(); $("copy").textContent = "Press Ctrl+C"; }
  setTimeout(() => $("copy").textContent = "Copy manifest code", 1600);
});
const setHelp = (show) => { $("help").hidden = !show; try { localStorage.setItem("ae-help", show ? "" : "1"); } catch (e) {} };
$("helpOk").onclick = () => setHelp(false);
$("helpBtn").onclick = () => { showTab("numbers"); setHelp($("help").hidden); };
try { if (localStorage.getItem("ae-help")) $("help").hidden = true; } catch (e) {}

(async () => {
  const r = await fetch("/api/heroes"); const { heroes } = await r.json();
  $("hero").replaceChildren(...heroes.map(h => el("option", { value: h, text: h.replace(/_/g, " ") })));
  S.hero = heroes.includes("Piper") ? "Piper" : heroes[0]; $("hero").value = S.hero;
  refresh();
})();
</script>
</body>
</html>
"""
