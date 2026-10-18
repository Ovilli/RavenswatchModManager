// ---- game models in three.js: shared by the map and the 3D tile editor -------------
// Inlined where a page names this file in double braces, inside its module script, after
// THREE is loaded. A "part" is what the engine's scene JSON lists:
// {mesh, texture, swap_rb, color, decal}; a model file is fetched from
// api/file. Always through fetch, never `img.src = url`: the web editor routes
// fetch to its engine, not image loads.

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
const fileUrl = (rel) => "api/file?path=" + encodeURIComponent(rel);
const queue = { active: 0, waiting: [] };
function limited(fn) {
  return new Promise((res, rej) => {
    const run = () => { queue.active++; fn().then(res, rej).finally(() => { queue.active--; const nx = queue.waiting.shift(); if (nx) nx(); }); };
    queue.active < 6 ? run() : queue.waiting.push(run);
  });
}
async function loadTexture(rel, swap, anisotropy) {
  const img = await limited(async () => {
    const r = await fetch(fileUrl(rel));
    if (!r.ok) throw new Error(r.status);
    const url = URL.createObjectURL(await r.blob());
    try {
      return await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
    } finally { URL.revokeObjectURL(url); }
  });
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
  tex.anisotropy = anisotropy || 1;
  return tex;
}
const partKey = (p) => [p.mesh, p.texture || "", p.swap_rb, p.color || "", p.decal].join("|");
let DECAL_GEO = null;
// One part's geometry + material, made once per key in `cache`. `hooks.start()`
// runs when a load begins and `hooks.done()` when it settles (for a progress
// line); `anisotropy` comes from the page's renderer.
function modelAsset(p, cache, anisotropy, hooks = {}) {
  const key = partKey(p);
  let a = cache.get(key);
  if (!a) {
    hooks.start?.();
    a = { geometry: null, material: null };
    if (p.decal && !DECAL_GEO) DECAL_GEO = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
    a.ready = Promise.all([
      p.decal ? Promise.resolve(DECAL_GEO)
        : limited(() => fetch(fileUrl(p.mesh)).then(r => { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); })).then(parseGlb),
      p.texture ? loadTexture(p.texture, p.swap_rb, anisotropy).catch(() => null) : Promise.resolve(null),
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
    }).catch(() => null).finally(() => hooks.done?.());
    cache.set(key, a);
  }
  return a;
}
const b64f32 = (s) => { const raw = Uint8Array.from(atob(s), c => c.charCodeAt(0)); return new Float32Array(raw.buffer); };
