/**
 * Pull `manifest.toml` out of a mod archive in the browser, so the publish form
 * can fill itself in instead of asking for what the archive already says.
 *
 * Only the zip's central directory and the one member are read — the archive
 * itself is never loaded whole — and nothing here is trusted: sizes are capped
 * on the compressed AND the inflated side (a header can lie about its inflated
 * size), zip64 and encrypted entries are declined, and every failure resolves to
 * `null`. The upload is unaffected either way.
 */

const MAX_MANIFEST_BYTES = 256 * 1024;
const MAX_CENTRAL_DIRECTORY = 8 * 1024 * 1024;
const EOCD_SIG = 0x06054b50;
const CENTRAL_SIG = 0x02014b50;
const LOCAL_SIG = 0x04034b50;

const ROOT = /^manifest\.toml$/i;
const ONE_DOWN = /^[^/\\]+\/manifest\.toml$/i;

async function inflate(raw: Blob): Promise<string | null> {
  if (typeof DecompressionStream === 'undefined') return null;
  const stream = raw.stream().pipeThrough(new DecompressionStream('deflate-raw'));
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_MANIFEST_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.byteLength;
  }
  return new TextDecoder('utf-8').decode(out);
}

/** The archive's `manifest.toml` (root, else one folder down) as text, or null. */
export async function readManifestText(file: Blob): Promise<string | null> {
  try {
    const tailLen = Math.min(file.size, 65_557);
    const tail = new DataView(await file.slice(file.size - tailLen).arrayBuffer());
    let eocd = -1;
    for (let i = tailLen - 22; i >= 0; i--) {
      if (tail.getUint32(i, true) === EOCD_SIG) {
        eocd = i;
        break;
      }
    }
    if (eocd < 0) return null;

    const count = tail.getUint16(eocd + 10, true);
    const cdSize = tail.getUint32(eocd + 12, true);
    const cdOffset = tail.getUint32(eocd + 16, true);
    if (cdSize === 0xffffffff || cdOffset === 0xffffffff) return null; // zip64
    if (cdSize > MAX_CENTRAL_DIRECTORY || cdOffset + cdSize > file.size) return null;

    const cd = new DataView(await file.slice(cdOffset, cdOffset + cdSize).arrayBuffer());
    let best: { rank: number; method: number; csize: number; usize: number; local: number } | null =
      null;
    let p = 0;
    for (let n = 0; n < count && p + 46 <= cd.byteLength; n++) {
      if (cd.getUint32(p, true) !== CENTRAL_SIG) break;
      const flags = cd.getUint16(p + 8, true);
      const method = cd.getUint16(p + 10, true);
      const csize = cd.getUint32(p + 20, true);
      const usize = cd.getUint32(p + 24, true);
      const nameLen = cd.getUint16(p + 28, true);
      const extraLen = cd.getUint16(p + 30, true);
      const commentLen = cd.getUint16(p + 32, true);
      const local = cd.getUint32(p + 42, true);
      const name = new TextDecoder().decode(new Uint8Array(cd.buffer, p + 46, nameLen));
      p += 46 + nameLen + extraLen + commentLen;
      const rank = ROOT.test(name) ? 0 : ONE_DOWN.test(name) ? 1 : -1;
      if (rank < 0 || flags & 1) continue; // not it, or encrypted
      if (!best || rank < best.rank) best = { rank, method, csize, usize, local };
    }
    if (!best || best.usize > MAX_MANIFEST_BYTES || best.csize > MAX_MANIFEST_BYTES) return null;

    const head = new DataView(await file.slice(best.local, best.local + 30).arrayBuffer());
    if (head.byteLength < 30 || head.getUint32(0, true) !== LOCAL_SIG) return null;
    const start = best.local + 30 + head.getUint16(26, true) + head.getUint16(28, true);
    const data = file.slice(start, start + best.csize);

    if (best.method === 0) return new TextDecoder('utf-8').decode(await data.arrayBuffer());
    if (best.method === 8) return await inflate(data);
    return null;
  } catch {
    return null;
  }
}
