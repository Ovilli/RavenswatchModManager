/**
 * What an uploaded mod archive contains, for the store's own "Private games
 * only" check (`@rsmm/schemas` modScopeReasons). Runs on the bytes the scan
 * already holds (scan-service), so the label never depends on what the
 * uploader's manifest says.
 *
 * Only the central directory and the members the check reads (manifest.toml
 * and Lua) are inflated, each capped on the inflated side. Nothing here is
 * trusted: zip64, encrypted or oversized members, and any archive the reader
 * cannot follow, come back as a reason, so the check fails closed.
 */
import { inflateRawSync } from 'node:zlib';
import { type ModFile, modScopeReasons } from '@rsmm/schemas';

const EOCD_SIG = 0x06054b50;
const CENTRAL_SIG = 0x02014b50;
const LOCAL_SIG = 0x04034b50;
const MAX_TEXT_BYTES = 2 * 1024 * 1024; // one manifest or Lua file
const MAX_TEXT_TOTAL = 32 * 1024 * 1024; // all of them together

interface Entry {
  name: string;
  method: number;
  flags: number;
  compressed: number;
  size: number;
  local: number;
}

/** Central directory entries, or a reason the archive cannot be read. */
function entries(buf: Buffer): Entry[] | string {
  const tail = Math.max(0, buf.length - 0xffff - 22);
  let eocd = -1;
  for (let i = buf.length - 22; i >= tail; i--) {
    if (buf.readUInt32LE(i) === EOCD_SIG) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) return 'is not a zip archive';
  const count = buf.readUInt16LE(eocd + 10);
  const cdSize = buf.readUInt32LE(eocd + 12);
  const cdOffset = buf.readUInt32LE(eocd + 16);
  if (count === 0xffff || cdOffset === 0xffffffff || cdSize === 0xffffffff) {
    return 'is a zip64 archive, which the store cannot check';
  }
  if (cdOffset + cdSize > buf.length) return 'has a broken central directory';
  const out: Entry[] = [];
  let p = cdOffset;
  for (let k = 0; k < count; k++) {
    if (p + 46 > buf.length || buf.readUInt32LE(p) !== CENTRAL_SIG) {
      return 'has a broken central directory';
    }
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    out.push({
      flags: buf.readUInt16LE(p + 8),
      method: buf.readUInt16LE(p + 10),
      compressed: buf.readUInt32LE(p + 20),
      size: buf.readUInt32LE(p + 24),
      local: buf.readUInt32LE(p + 42),
      name: buf.toString('utf8', p + 46, p + 46 + nameLen),
    });
    p += 46 + nameLen + extraLen + commentLen;
  }
  return out;
}

/** A member's bytes, or a reason it cannot be read. */
function read(buf: Buffer, e: Entry): Buffer | string {
  if (e.flags & 1) return 'is encrypted';
  if (e.size > MAX_TEXT_BYTES || e.compressed > MAX_TEXT_BYTES) return 'is too large to check';
  const at = e.local;
  if (at + 30 > buf.length || buf.readUInt32LE(at) !== LOCAL_SIG) return 'cannot be found';
  const start = at + 30 + buf.readUInt16LE(at + 26) + buf.readUInt16LE(at + 28);
  const raw = buf.subarray(start, start + e.compressed);
  if (raw.length !== e.compressed) return 'is cut short';
  if (e.method === 0) return raw;
  if (e.method !== 8) return 'uses a compression the store cannot read';
  try {
    return inflateRawSync(raw, { maxOutputLength: MAX_TEXT_BYTES });
  } catch {
    return 'cannot be inflated';
  }
}

/** The mod's files (paths inside its folder), with manifest and Lua text. */
export function modArchiveFiles(buf: Buffer): ModFile[] | string {
  const list = entries(buf);
  if (typeof list === 'string') return list;
  const names = list.filter((e) => !e.name.endsWith('/')).map((e) => e.name.replace(/\\/g, '/'));
  // The mod folder: where manifest.toml sits, at the root or one folder down
  // (`rsmm pack` writes `<id>/manifest.toml`).
  const manifest = names
    .filter((n) => /^(?:[^/]+\/)?manifest\.toml$/i.test(n))
    .sort((a, b) => a.length - b.length)[0];
  const root = manifest ? manifest.slice(0, manifest.length - 'manifest.toml'.length) : '';
  const files: ModFile[] = [];
  let total = 0;
  for (const e of list) {
    const name = e.name.replace(/\\/g, '/');
    if (name.endsWith('/')) continue;
    // A file outside the mod folder still installs; it is checked as if in it.
    const path = name.startsWith(root) ? name.slice(root.length) : name;
    const lower = path.toLowerCase();
    if (lower === 'manifest.toml' || lower.endsWith('.lua')) {
      const got = read(buf, e);
      if (typeof got === 'string' || total + got.length > MAX_TEXT_TOTAL) {
        files.push({ path, text: null });
        continue;
      }
      total += got.length;
      files.push({ path, text: got.toString('utf8') });
    } else {
      files.push({ path });
    }
  }
  return files;
}

/** Why the archive's mod changes the game the party plays (empty: it does not). */
export function modArchiveScopeReasons(buf: Buffer): string[] {
  const files = modArchiveFiles(buf);
  if (typeof files === 'string') return [`the archive ${files}`];
  return modScopeReasons(files);
}
