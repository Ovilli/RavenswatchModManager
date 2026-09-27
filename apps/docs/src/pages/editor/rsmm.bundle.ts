// /editor/rsmm.bundle — the `rsmm` Python package for the web editor, as a
// gzipped tar. Deliberately not named `.tar.gz`: some servers label that
// extension `Content-Encoding: gzip`, the browser then unzips it in flight, and
// the worker would be handed a plain tar. The worker sniffs the bytes instead.
//
// The editor page runs the real CLI code in the browser (Pyodide), so it needs
// the package source. This packs `src/rsmm` from the checkout at build time,
// which keeps the page and the engine on the same commit with nothing
// generated committed. Only the package is packed: no `data/`, nothing
// game-derived. The page rebuilds the asset map from the player's own install.
//
// The archive is deterministic (sorted paths, zero mtimes) so an unchanged
// engine gives a byte-identical file and stays cached.
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { gzipSync } from 'node:zlib';
import type { APIRoute } from 'astro';

/** Walk up from the build's working directory to the repo holding `src/rsmm`. */
function packageDir(): string {
  let dir = process.cwd();
  for (;;) {
    const candidate = join(dir, 'src', 'rsmm');
    if (existsSync(join(candidate, '__init__.py'))) return candidate;
    const up = dirname(dir);
    if (up === dir) throw new Error('web editor: src/rsmm not found above ' + process.cwd());
    dir = up;
  }
}

function files(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir).sort()) {
      if (name === '__pycache__' || name.endsWith('.pyc')) continue;
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else out.push(p);
    }
  };
  walk(root);
  return out;
}

/** One ustar header block. Names over 100 bytes go through the prefix field. */
function header(name: string, size: number): Buffer {
  const h = Buffer.alloc(512);
  let prefix = '';
  if (Buffer.byteLength(name) > 100) {
    const cut = name.lastIndexOf('/', 155);
    prefix = name.slice(0, cut);
    name = name.slice(cut + 1);
  }
  const put = (off: number, len: number, text: string) => h.write(text, off, len, 'utf8');
  const oct = (off: number, len: number, n: number) => put(off, len, n.toString(8).padStart(len - 1, '0') + '\0');
  put(0, 100, name);
  oct(100, 8, 0o644);
  oct(108, 8, 0);
  oct(116, 8, 0);
  oct(124, 12, size);
  oct(136, 12, 0);
  put(148, 8, '        '); // checksum is computed with this field as spaces
  put(156, 1, '0');
  put(257, 6, 'ustar\0');
  put(263, 2, '00');
  put(345, 155, prefix);
  let sum = 0;
  for (const b of h) sum += b;
  put(148, 8, sum.toString(8).padStart(6, '0') + '\0 ');
  return h;
}

export function packRsmm(): Buffer {
  const root = packageDir();
  const base = resolve(root, '..');
  const parts: Buffer[] = [];
  for (const path of files(root)) {
    const data = readFileSync(path);
    parts.push(header(relative(base, path).split(sep).join('/'), data.length), data);
    const pad = (512 - (data.length % 512)) % 512;
    if (pad) parts.push(Buffer.alloc(pad));
  }
  parts.push(Buffer.alloc(1024)); // end of archive
  return gzipSync(Buffer.concat(parts), { level: 9 });
}

export const GET: APIRoute = () =>
  new Response(new Uint8Array(packRsmm()), { headers: { 'Content-Type': 'application/octet-stream' } });
