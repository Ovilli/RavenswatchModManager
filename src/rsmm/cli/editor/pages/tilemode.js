// ---- the Map tab's 3D tile mode -----------------------------------------------------
// Inlined into map.html (render() fills its placeholder), after models.js (parseGlb,
// modelAsset, b64f32) and with THREE loaded. Everything lives in this closure
// and in elements whose ids start with "t3-", so it never meets the chapter
// editor's own state. TileMode.open(tilePath) shows it over the map;
// Back hides it again with the chapter untouched.
//
// A chapter is generated from tiles, so an object stands inside a TILE and
// appears wherever that tile spawns. What the author adds is saved as a poi
// def in replace_base mode with `places` (see rsmm.engine.tile_editor).
const TileMode = (() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
  const status = (text, cls = "") => { $("t3-status").textContent = text; $("t3-status").className = cls; };
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* no storage: fine */ } },
  };
  const DRAFT = "rsmm.tiles.draft.";
  // tile: path; data: the engine's objects JSON; added: what the author places.
  const S = { active: false, tiles: null, tile: null, data: null, added: [], sel: null, props: null, mods: [], showGame: true, onClose: null };
  let nextId = 1;

  // The engine is left-handed (Y up, +Z away) and WebGL right-handed: objects
  // live under one group mirrored in Z, so engine positions and rotations are
  // used unchanged (the chapter view does the same).
  const G = { ok: false, cache: new Map(), entities: new Map(), loading: 0, loaded: 0, keys: new Set(), dirty: true,
    cam: { pos: null, yaw: Math.PI * 0.75, pitch: -0.55, speed: 12 } };

  function glInit() {
    if (G.ok) return true;
    if (!THREE) return false;
    const cv = $("t3-gl");
    let renderer;
    try { renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true }); } catch { return false; }
    renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(getComputedStyle(document.body).getPropertyValue("--view").trim() || "#202024");
    const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 2000);
    const world = new THREE.Group(); world.scale.z = -1; scene.add(world);
    scene.add(new THREE.HemisphereLight(0xdfe8f2, 0x3d3a2c, 1.5));
    const sun = new THREE.DirectionalLight(0xfff0d8, 2.2); sun.position.set(-30, 60, 25); scene.add(sun);
    const grid = new THREE.GridHelper(80, 80, 0x8a7a5a, 0x55524a); grid.material.transparent = true; grid.material.opacity = 0.35;
    world.add(grid);
    const groups = { game: new THREE.Group(), added: new THREE.Group() };
    world.add(groups.game, groups.added);
    const box = new THREE.Box3Helper(new THREE.Box3(), 0xd6ac5c); box.visible = false; world.add(box);
    G.cam.pos = new THREE.Vector3(18, 16, -18);
    Object.assign(G, { ok: true, renderer, scene, camera, world, groups, box, ray: new THREE.Raycaster() });
    bindInput(cv);
    new ResizeObserver(() => { G.dirty = true; }).observe(cv);
    let last = performance.now();
    const frame = (now) => { requestAnimationFrame(frame); if (S.active) tick(Math.min(0.1, (now - last) / 1000)); last = now; };
    requestAnimationFrame(frame);
    return true;
  }

  function viewDir() {
    const c = G.cam, cp = Math.cos(c.pitch);
    return new THREE.Vector3(Math.sin(c.yaw) * cp, Math.sin(c.pitch), Math.cos(c.yaw) * cp);
  }
  function tick(dt) {
    const c = G.cam, k = G.keys;
    if (k.size && !document.activeElement?.matches?.("input, select, textarea")) {
      const fwd = viewDir(), right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize();
      const v = new THREE.Vector3();
      if (k.has("KeyW")) v.add(fwd); if (k.has("KeyS")) v.sub(fwd);
      if (k.has("KeyD")) v.add(right); if (k.has("KeyA")) v.sub(right);
      if (k.has("KeyE") || k.has("Space")) v.y += 1; if (k.has("KeyQ")) v.y -= 1;
      if (v.lengthSq()) { c.pos.addScaledVector(v.normalize(), c.speed * (k.has("ShiftLeft") || k.has("ShiftRight") ? 3 : 1) * dt); G.dirty = true; }
    }
    if (!G.dirty) return;
    const cv = $("t3-gl"), w = cv.clientWidth, h = cv.clientHeight; if (!w || !h) return;
    const size = G.renderer.getSize(new THREE.Vector2());
    if (size.x !== w || size.y !== h) G.renderer.setSize(w, h, false);
    G.camera.aspect = w / h; G.camera.updateProjectionMatrix();
    G.camera.position.copy(c.pos); G.camera.lookAt(c.pos.clone().add(viewDir()));
    G.dirty = false;
    G.renderer.render(G.scene, G.camera);
    hud();
  }

  // ---- entities -> meshes --------------------------------------------------------
  function entityTemplate(ref) {
    if (!G.entities.has(ref)) G.entities.set(ref, api("api/t3/entity?ref=" + encodeURIComponent(ref)).then(async (data) => {
      const tpl = new THREE.Group();
      await Promise.all((data.parts || []).map(async (part, i) => {
        const a = await modelAsset(part, G.cache, Math.min(8, G.renderer.capabilities.getMaxAnisotropy()),
          { start: () => { G.loading++; progress(); }, done: () => { G.loaded++; progress(); } }).ready;
        if (!a) return;
        const mats = b64f32(data.matrices[i]);
        for (let j = 0; j < mats.length; j += 16) {
          const m = new THREE.Mesh(a.geometry, a.material);
          m.matrixAutoUpdate = false; m.matrix.fromArray(mats, j);
          if (a.decal) m.renderOrder = 1;
          tpl.add(m);
        }
      }));
      return tpl;
    }).catch(() => new THREE.Group()));
    return G.entities.get(ref);
  }
  // A stand-in for an entity that draws nothing (a light, a trigger): still
  // selectable, so it can be found in the outliner and the view.
  const marker = (color) => new THREE.Mesh(new THREE.OctahedronGeometry(0.35), new THREE.MeshBasicMaterial({ color, wireframe: true }));
  function progress() {
    const busy = G.loaded < G.loading;
    $("t3-load").textContent = busy ? `Loading models ${G.loaded}/${G.loading}…` : ""; $("t3-load").hidden = !busy;
    G.dirty = true;
  }
  const yawQuat = (deg) => { const h = deg * Math.PI / 360; return new THREE.Quaternion(0, Math.sin(h), 0, Math.cos(h)); };
  function placeMatrix(o) {
    return o.kind === "game"
      ? new THREE.Matrix4().compose(new THREE.Vector3(...o.pos), new THREE.Quaternion(...o.quat), new THREE.Vector3(...o.scale))
      : new THREE.Matrix4().compose(new THREE.Vector3(...o.pos), yawQuat(o.yaw), new THREE.Vector3(o.scale, o.scale, o.scale));
  }
  // The node goes into the scene at once (empty) and fills in when its model arrives.
  function objectNode(o, group) {
    const node = new THREE.Group(); node.matrixAutoUpdate = false; node.matrix.copy(placeMatrix(o));
    node.userData.obj = o; o.node = node; group.add(node);
    entityTemplate(o.entity).then((tpl) => {
      if (o.node !== node) return;                   // replaced while loading
      node.add(tpl.children.length ? tpl.clone() : marker(o.kind === "game" ? 0x8a8a90 : 0x3ccb7f));
      G.dirty = true; if (S.sel === o) select(o);
    });
    return node;
  }
  function syncNode(o) { if (o.node) { o.node.matrix.copy(placeMatrix(o)); o.node.matrixWorldNeedsUpdate = true; } if (S.sel === o) select(o); G.dirty = true; }
  function drawTile() {
    G.groups.game.clear(); G.groups.added.clear();
    if (!S.data) return;
    for (const o of S.data.objects) objectNode(o, G.groups.game);
    for (const o of S.added) objectNode(o, G.groups.added);
  }

  // ---- picking, the fly camera and moving what you added -------------------------
  function pointerRay(ev) {
    const r = $("t3-gl").getBoundingClientRect();
    G.ray.setFromCamera(new THREE.Vector2((ev.clientX - r.left) / r.width * 2 - 1, -(ev.clientY - r.top) / r.height * 2 + 1), G.camera);
    return G.ray;
  }
  function pick(ev) {
    const roots = [G.groups.added, ...(S.showGame ? [G.groups.game] : [])];
    for (const hit of pointerRay(ev).intersectObjects(roots, true)) {
      let n = hit.object; while (n && !n.userData.obj) n = n.parent;
      if (n) return n.userData.obj;
    }
    return null;
  }
  // Where a ray meets the horizontal plane at height y, in engine space.
  // Mirroring Z keeps a horizontal plane horizontal, so only the point converts.
  function onPlane(ray, y) {
    const out = new THREE.Vector3();
    if (!ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -y), out)) return null;
    return G.world.worldToLocal(out);
  }
  function bindInput(cv) {
    let drag = null, looking = false, lx = 0, ly = 0, downAt = null;
    cv.addEventListener("contextmenu", (e) => e.preventDefault());
    cv.addEventListener("pointerdown", (e) => {
      cv.focus(); cv.setPointerCapture(e.pointerId); lx = e.clientX; ly = e.clientY;
      if (e.button === 2 || e.button === 1) { looking = true; return; }
      downAt = { x: e.clientX, y: e.clientY };
      const o = pick(e);
      if (o && o.kind === "added" && o === S.sel) drag = { o, start: o.pos.slice(), sy: e.clientY };
    });
    cv.addEventListener("pointermove", (e) => {
      const dx = e.clientX - lx, dy = e.clientY - ly; lx = e.clientX; ly = e.clientY;
      if (looking) { G.cam.yaw -= dx * 0.004; G.cam.pitch = Math.max(-1.5, Math.min(1.5, G.cam.pitch - dy * 0.004)); G.dirty = true; return; }
      if (!drag) return;
      if (e.altKey) {                                     // Alt: up and down
        drag.o.pos[1] = +(drag.start[1] + (drag.sy - e.clientY) * 0.03).toFixed(3);
      } else {
        const p = onPlane(pointerRay(e), drag.o.pos[1]); if (!p) return;
        if (!drag.off) drag.off = [drag.o.pos[0] - p.x, drag.o.pos[2] - p.z];
        drag.o.pos[0] = +(p.x + drag.off[0]).toFixed(3); drag.o.pos[2] = +(p.z + drag.off[1]).toFixed(3);
      }
      syncNode(drag.o); changed(false);
    });
    cv.addEventListener("pointerup", (e) => {
      if (looking) { looking = false; return; }
      if (drag) { drag = null; changed(); inspector(); return; }
      if (downAt && Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) < 5) select(pick(e));
      downAt = null;
    });
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      G.cam.speed = Math.max(1, Math.min(200, G.cam.speed * (e.deltaY > 0 ? 1 / 1.15 : 1.15))); G.dirty = true;
    }, { passive: false });
    window.addEventListener("keydown", (e) => {
      if (!S.active || e.target.matches?.("input, select, textarea")) return;
      G.keys.add(e.code); G.dirty = true;
      const o = S.sel;
      if (e.code === "KeyF" && o) focus(o);
      else if (e.code === "Escape") { if (o) select(null); else close(); }
      else if (o && o.kind === "added") {
        if (e.code === "KeyR") { o.yaw = norm(o.yaw + (e.shiftKey ? -15 : 15)); syncNode(o); changed(); inspector(); }
        else if (e.code === "Equal" || e.code === "NumpadAdd") { o.scale = clampScale(o.scale * 1.1); syncNode(o); changed(); inspector(); }
        else if (e.code === "Minus" || e.code === "NumpadSubtract") { o.scale = clampScale(o.scale / 1.1); syncNode(o); changed(); inspector(); }
        else if (e.code === "Delete" || e.code === "Backspace") { e.preventDefault(); remove(o); }
        else if (e.code === "KeyD" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); duplicate(o); }
      }
    });
    window.addEventListener("keyup", (e) => G.keys.delete(e.code));
    window.addEventListener("blur", () => G.keys.clear());
  }
  const norm = (deg) => +(((deg % 360) + 540) % 360 - 180).toFixed(3);
  const clampScale = (v) => +Math.max(0.05, Math.min(20, v)).toFixed(4);
  function focus(o) {
    const b = new THREE.Box3().setFromObject(o.node || new THREE.Object3D());
    const c = b.isEmpty() ? G.world.localToWorld(new THREE.Vector3(...o.pos)) : b.getCenter(new THREE.Vector3());
    const r = b.isEmpty() ? 2 : Math.max(1.5, b.getSize(new THREE.Vector3()).length() / 2);
    G.cam.pos.copy(c).addScaledVector(viewDir(), -r * 2.6); G.dirty = true;
  }

  // ---- editing -------------------------------------------------------------------
  function select(o) {
    S.sel = o || null;
    if (o && o.node) {
      const b = new THREE.Box3().setFromObject(o.node);
      if (b.isEmpty()) b.setFromCenterAndSize(G.world.localToWorld(new THREE.Vector3(...o.pos)), new THREE.Vector3(0.8, 0.8, 0.8));
      G.box.box.copy(b.applyMatrix4(G.world.matrixWorld.clone().invert())); G.box.visible = true;
    } else G.box.visible = false;
    G.dirty = true; outliner(); inspector();
  }
  function addProp(p) {
    if (!S.tile) return;
    const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2(0, 0), G.camera);
    let at = onPlane(ray, 0);
    if (!at || at.distanceTo(G.world.worldToLocal(G.cam.pos.clone())) > 60)
      at = G.world.worldToLocal(G.cam.pos.clone().addScaledVector(viewDir(), 8)).setY(0);
    const o = { kind: "added", id: nextId++, entity: p.entity, name: p.name, pos: [+at.x.toFixed(3), 0, +at.z.toFixed(3)], yaw: 0, scale: 1 };
    S.added.push(o); objectNode(o, G.groups.added); changed(); select(o);
  }
  function duplicate(o) {
    const c = { ...o, id: nextId++, pos: [o.pos[0] + 1, o.pos[1], o.pos[2] + 1], node: null };
    S.added.push(c); objectNode(c, G.groups.added); changed(); select(c);
  }
  function remove(o) {
    S.added = S.added.filter((x) => x !== o);
    if (o.node) G.groups.added.remove(o.node);
    changed(); select(null);
  }
  const placeOf = (o) => ({ entity: o.entity, pos: o.pos, yaw: o.yaw, scale: o.scale });
  function changed(save = true) {
    G.dirty = true;
    if (save && S.tile) store.set(DRAFT + S.tile, S.added.map(placeOf));
    $("t3-check").disabled = $("t3-save").disabled = !S.tile;
    if (save) outliner();
  }

  // ---- panels --------------------------------------------------------------------
  function outliner() {
    const row = (o) => el("li", { className: o.kind + (S.sel === o ? " sel" : ""), title: o.entity, onclick: () => select(o), ondblclick: () => focus(o) },
      el("span", { textContent: o.name }));
    $("t3-added").replaceChildren(...S.added.map(row));
    $("t3-addedn").textContent = S.added.length ? `(${S.added.length})` : "";
    const game = S.data ? S.data.objects : [];
    $("t3-game").replaceChildren(...game.map(row));
    $("t3-gamen").textContent = game.length ? `(${game.length})` : "";
  }
  function inspector() {
    const o = S.sel, box = $("t3-insp");
    if (!o) { box.replaceChildren(el("h2", { textContent: "Selection" }), el("p", { className: "hint", textContent: "Click an object in the view or the list." })); return; }
    const editable = o.kind === "added";
    const num = (v, on, step = "0.1") => el("input", { type: "number", step, value: v, disabled: !editable,
      oninput: (e) => { const x = parseFloat(e.target.value); if (Number.isFinite(x)) { on(x); syncNode(o); changed(false); } },
      onchange: () => changed() });
    const kids = [el("h2", { textContent: editable ? "Added object" : "The game's object (locked)" }),
      el("div", { className: "name", textContent: o.name }), el("div", { className: "path", textContent: o.entity }),
      el("label", {}, "Position", el("div", { className: "xyz" }, ...[0, 1, 2].map((k) => num(o.pos[k], (x) => { o.pos[k] = x; }))))];
    if (editable) {
      kids.push(el("label", {}, "Yaw °", num(o.yaw, (x) => { o.yaw = norm(x); }, "5")),
        el("label", {}, "Scale", num(o.scale, (x) => { o.scale = clampScale(x); }, "0.05")),
        el("div", { className: "row" },
          el("button", { className: "btn", textContent: "Focus (F)", onclick: () => focus(o) }),
          el("button", { className: "btn", textContent: "Duplicate", onclick: () => duplicate(o) }),
          el("button", { className: "btn", textContent: "Delete", onclick: () => remove(o) })),
        el("p", { className: "hint", innerHTML: "Drag it in the view to move; hold <kbd>Alt</kbd> to raise or lower. <kbd>R</kbd> turns 15°, <kbd>+</kbd>/<kbd>−</kbd> scale, <kbd>Ctrl</kbd>+<kbd>D</kbd> duplicate, <kbd>Del</kbd> delete." }));
    } else {
      const q = o.quat, tilt = Math.acos(Math.max(-1, Math.min(1, 1 - 2 * (q[0] * q[0] + q[2] * q[2])))) * 180 / Math.PI;
      kids.push(el("label", {}, "Yaw °", num(+(2 * Math.atan2(q[1], q[3]) * 180 / Math.PI).toFixed(1), () => {})),
        el("label", {}, "Scale", num(o.scale.map((v) => +v.toFixed(3)).join(" × "), () => {})),
        el("p", { className: "hint", textContent: (tilt > 1 ? `Tilted ${tilt.toFixed(0)}°. ` : "") + "Moving or removing the game's own objects is not supported yet; add objects around them." }),
        el("div", { className: "row" }, el("button", { className: "btn", textContent: "Focus (F)", onclick: () => focus(o) })));
    }
    box.replaceChildren(...kids);
  }
  function hud() {
    $("t3-hud").innerHTML = `speed ${G.cam.speed.toFixed(0)} · hold <kbd>right mouse</kbd> to look, <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> move, `
      + "<kbd>Q</kbd>/<kbd>E</kbd> down/up, <kbd>Shift</kbd> fast, wheel = speed, <kbd>F</kbd> focus, <kbd>Esc</kbd> back";
  }
  function renderProps() {
    const q = $("t3-propq").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const list = (S.props || []).filter((p) => q.every((w) => p.entity.toLowerCase().includes(w))).slice(0, 150);
    $("t3-props").replaceChildren(...list.map((p) => el("li", { title: p.entity, onclick: () => addProp(p) },
      el("span", { textContent: p.name }), el("small", { textContent: p.group }))));
  }

  // ---- tiles, mods, saving -------------------------------------------------------
  async function load(path, places) {
    S.tile = path; S.data = null; S.added = []; select(null);
    $("t3-title").textContent = path.split("\\").pop().replace(".tiledef.ot", "").replace(/_/g, " ");
    $("t3-empty").hidden = false; $("t3-empty").textContent = "Loading the tile…";
    G.groups.game.clear(); G.groups.added.clear(); outliner();
    try { S.data = await api("api/t3/objects?tile=" + encodeURIComponent(path)); }
    catch (e) { if (S.tile === path) $("t3-empty").textContent = e.message; return; }
    if (S.tile !== path) return;
    for (const o of S.data.objects) o.kind = "game";
    const draft = places || store.get(DRAFT + path) || [];
    S.added = draft.map((p) => ({ kind: "added", id: nextId++, entity: p.entity, name: p.entity.split("\\").pop().replace(".entity.ot", ""),
      pos: p.pos.slice(), yaw: p.yaw || 0, scale: p.scale || 1 }));
    $("t3-empty").hidden = true;
    G.cam.pos.set(18, 16, -18); G.cam.yaw = Math.PI * 0.75; G.cam.pitch = -0.55;
    drawTile(); outliner(); changed(false);
    status(S.data.chapters.length ? `Drawn by ${S.data.chapters.join(", ").replace(/_/g, " ")}.`
      : "No chapter this editor can extend draws this tile; it can be viewed, not saved.", S.data.chapters.length ? "" : "st-bad");
  }
  const body = () => ({ tile: S.tile, places: S.added.map(placeOf), mod_id: $("t3-modid").value.trim().toLowerCase(), name: $("t3-modname").value.trim() });
  async function check() {
    if (!S.added.length) { status("Add an object first.", "st-bad"); return; }
    status("Checking…");
    try { const r = await api("api/t3/check", body()); status(`OK: the mod would write ${r.files.length} file(s).`, "st-ok"); }
    catch (e) { status(e.message, "st-bad"); }
  }
  async function save() {
    const b = body();
    if (!b.mod_id) { status("Give the mod an id first.", "st-bad"); $("t3-modid").focus(); return; }
    status("Saving…");
    try {
      const r = await api("api/t3/save", b);
      status(window.RSMM_HOSTED ? `Saved ${b.mod_id} and downloaded ${b.mod_id}.zip. ${r.next}` : `Saved ${r.path}. ${r.next}`, "st-ok");
      await loadMods(); $("t3-modpick").value = b.mod_id;
    } catch (e) { status(e.message, "st-bad"); }
  }
  async function loadMods() {
    try { S.mods = (await api("api/t3/mods")).mods || []; } catch { S.mods = []; }
    $("t3-modpick").replaceChildren(el("option", { value: "", textContent: "New mod" }),
      ...S.mods.map((m) => el("option", { value: m.id, textContent: `${m.id} (${m.tiles.length} tile${m.tiles.length === 1 ? "" : "s"})` })));
  }
  function wire() {
    $("t3-back").onclick = close;
    $("t3-check").onclick = check; $("t3-save").onclick = save;
    $("t3-showgame").onchange = () => { S.showGame = $("t3-showgame").checked; G.groups.game.visible = S.showGame; G.dirty = true; };
    $("t3-propq").oninput = renderProps;
    $("t3-modpick").onchange = async () => {
      const id = $("t3-modpick").value; if (!id) { $("t3-modid").value = ""; $("t3-modname").value = ""; return; }
      try {
        const m = await api("api/t3/mod?id=" + encodeURIComponent(id));
        $("t3-modid").value = m.id; $("t3-modname").value = m.name || "";
        const places = m.tiles[S.tile];
        if (places) await load(S.tile, places);
        else {
          const [tile, saved] = Object.entries(m.tiles)[0] || [];
          if (tile) await load(tile, saved);
        }
      } catch (e) { status(e.message, "st-bad"); }
    };
  }

  let wired = false;
  async function open(tile, onClose) {
    if (!wired) { wire(); wired = true; }
    S.onClose = onClose || null;
    $("t3").hidden = false; S.active = true;
    if (!glInit()) { $("t3-empty").hidden = false; $("t3-empty").textContent = "This browser could not start WebGL, which the 3D view needs."; return; }
    G.dirty = true; hud();
    if (!S.props) api("api/t3/props").then((r) => { S.props = r.props; renderProps(); })
      .catch((e) => $("t3-props").replaceChildren(el("li", { textContent: e.message })));
    loadMods();
    await load(tile);
  }
  function close() {
    S.active = false; G.keys.clear(); $("t3").hidden = true;
    S.onClose?.();
  }
  return { open, close, active: () => S.active };
})();
