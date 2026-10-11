import { deflateRawSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { readManifestText } from './zip-manifest';

interface Entry {
  name: string;
  data: string;
  deflate?: boolean;
  /** Lie about the inflated size in the central directory. */
  claimedSize?: number;
}

/** Minimal zip writer: local headers, a central directory, an end record. */
function zip(entries: Entry[]): Blob {
  const parts: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const e of entries) {
    const raw = Buffer.from(e.data, 'utf-8');
    const body = e.deflate ? deflateRawSync(raw) : raw;
    const name = Buffer.from(e.name);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(e.deflate ? 8 : 0, 8);
    local.writeUInt32LE(body.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(name.length, 26);
    parts.push(local, name, body);
    const c = Buffer.alloc(46);
    c.writeUInt32LE(0x02014b50, 0);
    c.writeUInt16LE(20, 4);
    c.writeUInt16LE(20, 6);
    c.writeUInt16LE(e.deflate ? 8 : 0, 10);
    c.writeUInt32LE(body.length, 20);
    c.writeUInt32LE(e.claimedSize ?? raw.length, 24);
    c.writeUInt16LE(name.length, 28);
    c.writeUInt32LE(offset, 42);
    central.push(c, name);
    offset += local.length + name.length + body.length;
  }
  const cd = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(cd.length, 12);
  end.writeUInt32LE(offset, 16);
  return new Blob([Buffer.concat([...parts, cd, end])]);
}

const MANIFEST = '[mod]\nid = "demo"\nname = "Demo"\n';

describe('readManifestText', () => {
  it('reads a deflated manifest at the archive root', async () => {
    const z = zip([
      { name: 'a.txt', data: 'x' },
      { name: 'manifest.toml', data: MANIFEST, deflate: true },
    ]);
    expect(await readManifestText(z)).toBe(MANIFEST);
  });

  it('reads a stored manifest and one nested a folder down', async () => {
    expect(await readManifestText(zip([{ name: 'manifest.toml', data: MANIFEST }]))).toBe(MANIFEST);
    expect(
      await readManifestText(zip([{ name: 'demo/manifest.toml', data: MANIFEST, deflate: true }])),
    ).toBe(MANIFEST);
  });

  it('prefers the root manifest over a nested one', async () => {
    const z = zip([
      { name: 'sub/manifest.toml', data: 'nested' },
      { name: 'manifest.toml', data: MANIFEST },
    ]);
    expect(await readManifestText(z)).toBe(MANIFEST);
  });

  it('does not look deeper than one folder', async () => {
    expect(await readManifestText(zip([{ name: 'a/b/manifest.toml', data: MANIFEST }]))).toBeNull();
  });

  it('returns null for no manifest, for junk, and for an empty file', async () => {
    expect(await readManifestText(zip([{ name: 'readme.md', data: 'hi' }]))).toBeNull();
    expect(await readManifestText(new Blob(['definitely not a zip']))).toBeNull();
    expect(await readManifestText(new Blob([]))).toBeNull();
  });

  it('refuses an oversized manifest, including one whose header lies about its size', async () => {
    const big = 'x'.repeat(300 * 1024);
    expect(
      await readManifestText(zip([{ name: 'manifest.toml', data: big, deflate: true }])),
    ).toBeNull();
    // Header claims 10 bytes; the stream inflates to 300 KiB and is cut off.
    const liar = zip([{ name: 'manifest.toml', data: big, deflate: true, claimedSize: 10 }]);
    expect(await readManifestText(liar)).toBeNull();
  });
});
