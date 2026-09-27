// The web editor's engine: the real `rsmm` Python package, running in Pyodide.
//
// Messages in: {id, op, ...}; out: {id, ok, result | error} plus
// {progress: "..."} while booting.
//
//   init     load Pyodide and unpack /editor/rsmm.bundle (a gzipped tar)
//   mount    mount the player's DarkTalesResources (File objects from a folder
//            picker) and rebuild the asset map from its UsedRscList.ot
//   request  one editor HTTP request -> {status, headers, body}
//   zip      a saved mod folder as a .zip
//
// The game folder is mounted with Emscripten's WORKERFS: each file is read
// lazily with FileReaderSync when Python opens it, so a 7 GB install costs
// only the few megabytes the editors actually read. Nothing leaves the page.

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';

let py = null;

const send = (msg, transfer) => self.postMessage(msg, transfer || []);
const progress = (text) => send({ progress: text });

async function init({ bundle }) {
  progress('Downloading the Python runtime (about 12 MB, cached after the first visit)…');
  const { loadPyodide } = await import(`${PYODIDE}pyodide.mjs`);
  py = await loadPyodide({
    indexURL: PYODIDE,
    env: {
      HOME: '/home/pyodide',
      RSMM_REPO_ROOT: '/rsmm',
      RSMM_GAME_DIR: '/game',
      RSMM_MODS_DIR: '/mods',
    },
    stdout: () => {},
    stderr: (line) => console.warn('[rsmm]', line),
  });
  progress('Loading the rsmm engine…');
  const tar = await fetch(bundle).then((r) => {
    if (!r.ok) throw new Error(`rsmm bundle: HTTP ${r.status}`);
    return r.arrayBuffer();
  });
  for (const d of ['/rsmm/src', '/rsmm/data', '/game/DarkTalesResources', '/mods'])
    py.FS.mkdirTree(d);
  // Gzip unless something between here and the server already unzipped it.
  const head = new Uint8Array(tar, 0, 2);
  const format = head[0] === 0x1f && head[1] === 0x8b ? 'gztar' : 'tar';
  py.unpackArchive(tar, format, { extractDir: '/rsmm/src' });
  // paths.py finds the repo by its asset map; the real one is built at mount.
  py.FS.writeFile('/rsmm/data/asset_map.json', '{}');
  py.runPython(`
import sys
sys.path.insert(0, "/rsmm/src")
`);
  return { python: py.version };
}

async function mount({ files, paths }) {
  if (!py) throw new Error('the engine is not loaded');
  progress(`Opening your game folder (${files.length.toLocaleString()} files)…`);
  py.FS.mount(
    py.FS.filesystems.WORKERFS,
    { blobs: files.map((data, i) => ({ name: paths[i], data })) },
    '/game/DarkTalesResources',
  );
  progress("Reading the game's asset list…");
  const out = py.runPython(`
import contextlib, io, json
from pathlib import Path
from rsmm.engine import find_iyg

src = Path("/game/DarkTalesResources/UsedRscList.ot")
if not src.is_file():
    raise SystemExit("no UsedRscList.ot in that folder")
with contextlib.redirect_stdout(io.StringIO()):
    rc = find_iyg.main(str(src))
if rc:
    raise SystemExit("could not read the game's asset list (UsedRscList.ot)")

from rsmm.cli.editor import content
from rsmm.cli.editor.bridge import Bridge
bridge = Bridge()

def rsmm_request(method, path, body, headers_json):
    status, headers, data = bridge.request(method, path, body.to_bytes(),
                                           json.loads(headers_json))
    return status, json.dumps(headers), data

json.dumps({"items": len(content.items()), "heroes": len(content.heroes())})
`);
  return JSON.parse(out);
}

function request({ method, path, headers, body }) {
  const fn = py.globals.get('rsmm_request');
  const r = fn(method, path, body, JSON.stringify(headers || {}));
  try {
    const [status, headersJson, data] = r.toJs();
    return { status, headers: JSON.parse(headersJson), body: data };
  } finally {
    r.destroy();
    fn.destroy();
  }
}

function zip({ mod }) {
  const fn = py.runPython('bridge.zip_mod');
  const r = fn(mod);
  try {
    return r.toJs();
  } finally {
    r.destroy();
    fn.destroy();
  }
}

const OPS = { init, mount, request, zip };

// Anything that escapes a request (an error thrown later by Pyodide, a
// rejected promise nobody awaited) would otherwise reach the page as an error
// event with no message. Say what it was instead.
self.addEventListener('error', (e) => {
  send({ fatal: e.message || String(e.error || 'error in the engine') });
});
self.addEventListener('unhandledrejection', (e) => {
  send({ fatal: String(e.reason?.message || e.reason || 'unhandled rejection') });
});

self.onmessage = async (e) => {
  const { id, op, ...args } = e.data;
  try {
    const result = await OPS[op](args);
    const transfer = result?.body?.buffer
      ? [result.body.buffer]
      : result instanceof Uint8Array
        ? [result.buffer]
        : [];
    send({ id, ok: true, result }, transfer);
  } catch (err) {
    // A Python exception reaches here as a PythonError whose message is the
    // whole traceback; its last line is the part a person can act on.
    const text = String(err?.message || err);
    const last = text.trim().split('\n').pop();
    console.error(text);
    send({ id, ok: false, error: last || text });
  }
};
