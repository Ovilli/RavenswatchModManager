# ruff: noqa: E501  (the string below is HTML/JS, not Python)
"""The ability editor's single page: HTML, CSS and JS, no build step, no assets.

A Python module (not a data file) so the frozen CLI bundles it through
``--collect-submodules=rsmm.cli`` with no build-script change, like the map
editor's page. The graph is plain SVG with a layered layout; nothing
game-derived is embedded: every part, field and link comes from
``/api/graph``, which reads the user's own install at request time.

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
  --bg: #f4f3ef; --panel: #fff; --ink: #1d1d1f; --muted: #66666c; --line: #deddd8;
  --accent: #7a3cff; --ok: #1f9d55; --warn: #c77700; --bad: #c0392b; --chip: #efeee9;
  --node: #fff; --ext: #ecebe6; --edge: #9b9aa0; --sel: #7a3cff;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #151517; --panel: #1f1f22; --ink: #ececef; --muted: #9c9ca3; --line: #34343a;
          --chip: #2a2a2f; --node: #26262b; --ext: #1b1b1e; --edge: #6d6d75; }
}
* { box-sizing: border-box; }
body { margin: 0; font: 13px/1.4 system-ui, sans-serif; background: var(--bg); color: var(--ink);
       display: grid; grid-template: "top top top" auto "left mid right" 1fr "left steps right" auto / 240px 1fr 360px; height: 100vh; }
header { grid-area: top; display: flex; gap: 10px; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--line); background: var(--panel); }
header h1 { font-size: 15px; margin: 0 12px 0 0; }
select, input, button, textarea { font: inherit; color: inherit; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; }
button { cursor: pointer; } button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
#left { grid-area: left; overflow: auto; border-right: 1px solid var(--line); background: var(--panel); padding: 8px; }
#left input { width: 100%; margin-bottom: 6px; }
.grp { display: flex; justify-content: space-between; padding: 4px 6px; border-radius: 6px; cursor: pointer; }
.grp:hover { background: var(--chip); } .grp.on { background: var(--accent); color: #fff; }
.grp span { opacity: .7; }
#mid { grid-area: mid; position: relative; overflow: hidden; }
#mid svg { width: 100%; height: 100%; cursor: grab; }
#hint { position: absolute; left: 10px; bottom: 8px; color: var(--muted); font-size: 12px; }
#right { grid-area: right; overflow: auto; border-left: 1px solid var(--line); background: var(--panel); padding: 10px; }
#right h2 { font-size: 14px; margin: 0 0 2px; } .cls { color: var(--muted); margin-bottom: 8px; }
.f { border-top: 1px solid var(--line); padding: 6px 0; }
.f .n { font-weight: 600; } .f .k { color: var(--muted); font-size: 11px; margin-left: 4px; }
.f .t { word-break: break-word; color: var(--muted); margin: 2px 0 4px; }
.f .row { display: flex; gap: 4px; } .f .row > :first-child { flex: 1; min-width: 0; }
.item { display: flex; justify-content: space-between; gap: 4px; font-size: 12px; }
#steps { grid-area: steps; border-top: 1px solid var(--line); background: var(--panel); padding: 8px 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; max-height: 38vh; }
#steps ol { margin: 0; padding-left: 20px; overflow: auto; }
#steps li { margin: 2px 0; } #steps li button { padding: 0 6px; margin-left: 6px; }
#toml { width: 100%; height: 100%; min-height: 120px; font: 12px ui-monospace, monospace; resize: none; }
#status { margin-top: 6px; white-space: pre-wrap; font-size: 12px; }
.bad { color: var(--bad); } .ok { color: var(--ok); } .warn { color: var(--warn); }
g.node rect { fill: var(--node); stroke: var(--line); } g.node.ext rect { fill: var(--ext); stroke-dasharray: 3 3; }
g.node.sel rect { stroke: var(--sel); stroke-width: 2; } g.node text { fill: var(--ink); font-size: 12px; }
g.node .c { fill: var(--muted); font-size: 10px; } g.node { cursor: pointer; }
path.e { fill: none; stroke: var(--edge); stroke-width: 1.2; } text.el { fill: var(--muted); font-size: 10px; }
</style>
</head>
<body>
<header>
  <h1>Ability Editor</h1>
  <label>Hero <select id="hero"></select></label>
  <label>Entity <select id="entity"></select></label>
  <span id="busy" class="warn"></span>
</header>
<nav id="left"><input id="filter" placeholder="filter groups"><div id="groups"></div></nav>
<main id="mid"><svg id="svg"><g id="view"></g></svg><div id="hint">drag to pan, wheel to zoom, click a part to inspect it</div></main>
<aside id="right"><div id="insp" class="cls">Pick a group, then a part.</div></aside>
<section id="steps">
  <div><b>Steps</b> <button id="clear">clear</button><ol id="list"></ol><div id="status"></div></div>
  <div><b>Manifest</b> <button id="copy">copy</button><textarea id="toml" readonly></textarea></div>
</section>
<script>
const TOKEN = "__RSMM_TOKEN__";
const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElementNS(tag === "svg" || ["g","rect","text","path","defs"].includes(tag) ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml", tag);
  for (const [k, v] of Object.entries(attrs)) k === "text" ? e.textContent = v : k.startsWith("on") ? e.addEventListener(k.slice(2), v) : e.setAttribute(k, v);
  for (const k of kids) if (k) e.append(k);
  return e;
};
let S = { hero: "", entity: "", steps: [], data: null, group: "", sel: null, tf: { x: 40, y: 40, k: 1 } };

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-RSMM-Token": TOKEN }, body: JSON.stringify(body) });
  const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j;
}
async function refresh() {
  $("busy").textContent = "working…";
  try {
    S.data = await post("/api/graph", { hero: S.hero, entity: S.entity, steps: S.steps });
    S.entity = S.data.entity;
  } catch (e) { $("status").className = "bad"; $("status").textContent = e.message; $("busy").textContent = ""; return; }
  $("busy").textContent = "";
  const es = $("entity"); es.replaceChildren(...S.data.entities.map(n => el("option", { value: n, text: n })));
  es.value = S.entity;
  drawGroups(); drawSteps();
  if (!groupsOf().has(S.group)) S.group = [...groupsOf().keys()].find(g => g.startsWith("Ability")) || [...groupsOf().keys()][0] || "";
  drawGraph(); inspect(S.sel && byId(S.sel.id) ? S.sel.id : null);
}
const byId = (id) => S.data.components.find(c => c.id === id);
const groupsOf = () => { const m = new Map(); for (const c of S.data.components) m.set(c.group, (m.get(c.group) || 0) + 1); return new Map([...m].sort()); };

function drawGroups() {
  const f = $("filter").value.toLowerCase();
  $("groups").replaceChildren(...[...groupsOf()].filter(([g]) => g.toLowerCase().includes(f)).map(([g, n]) =>
    el("div", { class: "grp" + (g === S.group ? " on" : ""), onclick: () => { S.group = g; S.sel = null; S.tf = { x: 40, y: 40, k: 1 }; drawGroups(); drawGraph(); inspect(null); } },
      el("div", { text: g || "(no group)" }), el("span", { text: n }))));
}

function drawGraph() {
  const view = $("view"); view.replaceChildren();
  const inGroup = S.data.components.filter(c => c.group === S.group);
  const ids = new Set(inGroup.map(c => c.id));
  const edges = [], ext = new Map();
  for (const c of inGroup) for (const f of c.fields) for (const t of f.targets) {
    edges.push({ from: c.id, to: t, label: f.name });
    if (!ids.has(t)) { const tc = byId(t); ext.set(t, tc ? tc : { id: t, name: "(outside this entity)", group: "", cls: "", ext: true }); }
  }
  // Layered layout: a part sits one column right of the deepest part linking to it.
  const nodes = [...inGroup, ...ext.values()], depth = new Map(nodes.map(n => [n.id, 0]));
  for (let i = 0; i < nodes.length; i++) for (const e of edges) if (e.from !== e.to && depth.get(e.to) < depth.get(e.from) + 1 && depth.get(e.from) < 12) depth.set(e.to, depth.get(e.from) + 1);
  const cols = new Map(); for (const n of nodes) { const d = ids.has(n.id) ? depth.get(n.id) : Math.max(depth.get(n.id), 1); (cols.get(d) || cols.set(d, []).get(d)).push(n); }
  const W = 230, H = 44, pos = new Map();
  for (const [d, list] of [...cols].sort((a, b) => a[0] - b[0])) list.forEach((n, i) => pos.set(n.id, { x: d * (W + 90), y: i * (H + 22) }));
  for (const e of edges) {
    const a = pos.get(e.from), b = pos.get(e.to); if (!a || !b) continue;
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
    const d = e.from === e.to ? `M${x1},${y1} C${x1 + 40},${y1 - 40} ${x1 - 40},${y1 - 40} ${x1 - 20},${a.y}` : `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
    view.append(el("path", { class: "e", d, "marker-end": "url(#arrow)" }), el("text", { class: "el", x: mx - 20, y: (y1 + y2) / 2 - 3, text: e.label }));
  }
  for (const n of nodes) {
    const p = pos.get(n.id), isExt = !ids.has(n.id);
    view.append(el("g", { class: "node" + (isExt ? " ext" : "") + (S.sel && S.sel.id === n.id ? " sel" : ""), transform: `translate(${p.x},${p.y})`,
        onclick: (ev) => { ev.stopPropagation(); if (isExt && n.group !== undefined && byId(n.id)) { S.group = n.group; drawGroups(); drawGraph(); } inspect(n.id); } },
      el("rect", { width: W, height: H, rx: 8 }),
      el("text", { x: 10, y: 18, text: trim(n.name, 32) }),
      el("text", { class: "c", x: 10, y: 34, text: isExt ? (n.group ? "in " + n.group : "outside") : n.cls })));
  }
  applyTf();
}
const trim = (s, n) => s.length > n ? s.slice(0, n - 1) + "…" : s;
function applyTf() { $("view").setAttribute("transform", `translate(${S.tf.x},${S.tf.y}) scale(${S.tf.k})`); }

function inspect(id) {
  const box = $("right"); box.replaceChildren();
  const groupBtn = el("div", { class: "f" }, el("div", { class: "n", text: "Copy this ability" }),
    el("div", { class: "row" }, el("input", { id: "cloneAs", placeholder: "new group name, e.g. Echo" }),
      el("button", { text: "copy", onclick: () => { const as = $("cloneAs").value.trim(); if (as) addStep({ clone: S.group, as }); } })));
  if (!id) { box.append(el("div", { class: "cls", text: S.group ? "Group: " + S.group : "" }), groupBtn); return; }
  const c = byId(id); S.sel = c;
  if (!c) { box.append(el("div", { class: "cls", text: "That part is not in this entity (inherited or in another entity)." })); return; }
  box.append(el("h2", { text: c.name }), el("div", { class: "cls", text: c.cls + (c.group ? " · " + c.group : "") }));
  const partNames = S.data.components.map(x => x.name).sort();
  for (const f of c.fields) {
    const row = el("div", { class: "f" }, el("div", {}, el("span", { class: "n", text: f.name }), el("span", { class: "k", text: f.kind })),
      el("div", { class: "t", text: f.text }));
    const addr = `${c.name}.${f.name}`;
    const lit = literal(f);
    if (lit) {
      const inp = el("input", { value: lit.value });
      row.append(el("div", { class: "row" }, inp, el("button", { text: "set", onclick: () => { const v = lit.parse(inp.value); if (v !== undefined) addStep({ set: addr, value: v }); } })));
    }
    if (f.kind === "ref" || (f.kind === "value" && f.targets.length)) row.append(linkRow(partNames, (to) => addStep({ link: addr, to }), true));
    if (f.kind === "ref[]") {
      f.text.split("  |  ").forEach((t, i) => { if (f.items) row.append(el("div", { class: "item" }, el("span", { text: t.replace(/^<- /, "") }), el("button", { text: "remove", onclick: () => addStep({ remove_link: `${addr}[${i}]` }) }))); });
      row.append(linkRow(partNames, (to) => addStep({ add_link: addr, to }), false));
    }
    box.append(row);
  }
  box.append(groupBtn);
  drawGraph();
}
function linkRow(names, act, allowNone) {
  const sel = el("select", {}, ...(allowNone ? [el("option", { value: "", text: "(nothing)" })] : []), ...names.map(n => el("option", { value: n, text: n })));
  return el("div", { class: "row" }, sel, el("button", { text: allowNone ? "link" : "add", onclick: () => act(sel.value) }));
}
function literal(f) {
  if (["bool", "u32", "f32"].includes(f.kind)) return { value: f.text, parse: (s) => f.kind === "bool" ? /^(1|true|yes)$/i.test(s) : Number(s) };
  if (f.kind !== "value" || f.targets.length) return null;
  const m = f.text.match(/^(f32|int|bool|vec2|vec3|vec4) (.*)$/); if (!m) return null;
  if (m[1] === "bool") return { value: m[2], parse: (s) => /^(1|true|yes)$/i.test(s.trim()) };
  if (m[1].startsWith("vec")) return { value: m[2].split(" ").join(", "), parse: (s) => s.split(/[ ,]+/).filter(Boolean).map(Number) };
  return { value: m[2], parse: (s) => { const n = Number(s); return Number.isFinite(n) ? n : undefined; } };
}
function addStep(step) {
  if (S.entity && S.entity !== "Hero_" + S.hero) step.entity = S.entity;
  S.steps.push(step); refresh();
}
function drawSteps() {
  $("list").replaceChildren(...S.steps.map((s, i) => el("li", {}, el("span", { text: Object.entries(s).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join("  ") }),
    el("button", { text: "×", onclick: () => { S.steps.splice(i, 1); refresh(); } }))));
  $("toml").value = S.data.toml || "";
  const st = $("status");
  if (S.data.error) { st.className = "bad"; st.textContent = S.data.error; }
  else if (S.data.warnings.length) { st.className = "warn"; st.textContent = S.data.warnings.join("\n"); }
  else { st.className = "ok"; st.textContent = S.steps.length ? "All checks pass: this would build." : ""; }
}

// pan + zoom
let drag = null;
$("svg").addEventListener("mousedown", (e) => { drag = { x: e.clientX - S.tf.x, y: e.clientY - S.tf.y }; });
window.addEventListener("mousemove", (e) => { if (drag) { S.tf.x = e.clientX - drag.x; S.tf.y = e.clientY - drag.y; applyTf(); } });
window.addEventListener("mouseup", () => drag = null);
$("svg").addEventListener("wheel", (e) => { e.preventDefault(); const k = Math.min(3, Math.max(0.2, S.tf.k * (e.deltaY < 0 ? 1.1 : 0.9))); S.tf.x = e.offsetX - (e.offsetX - S.tf.x) * k / S.tf.k; S.tf.y = e.offsetY - (e.offsetY - S.tf.y) * k / S.tf.k; S.tf.k = k; applyTf(); }, { passive: false });
$("svg").prepend(el("defs", {}, (() => { const m = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  for (const [k, v] of Object.entries({ id: "arrow", viewBox: "0 0 10 10", refX: 10, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" })) m.setAttribute(k, v);
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path"); p.setAttribute("d", "M0,0 L10,5 L0,10 z"); p.setAttribute("fill", "currentColor"); m.append(p); return m; })()));
$("filter").addEventListener("input", drawGroups);
$("hero").addEventListener("change", () => { S.hero = $("hero").value; S.entity = ""; S.steps = []; S.group = ""; S.sel = null; refresh(); });
$("entity").addEventListener("change", () => { S.entity = $("entity").value; S.group = ""; S.sel = null; refresh(); });
$("clear").addEventListener("click", () => { S.steps = []; refresh(); });
$("copy").addEventListener("click", () => { navigator.clipboard.writeText($("toml").value); $("copy").textContent = "copied"; setTimeout(() => $("copy").textContent = "copy", 1200); });

(async () => {
  const r = await fetch("/api/heroes"); const { heroes } = await r.json();
  $("hero").replaceChildren(...heroes.map(h => el("option", { value: h, text: h })));
  S.hero = heroes.includes("Piper") ? "Piper" : heroes[0]; $("hero").value = S.hero;
  refresh();
})();
</script>
</body>
</html>
"""
