import { deflateRawSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { modArchiveFiles, modArchiveScopeReasons } from '../src/mod-archive.js';

/** A zip of `files` (name -> text), deflated unless `stored`. */
function zip(files: Record<string, string>, stored = false): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const [name, text] of Object.entries(files)) {
    const raw = Buffer.from(text, 'utf8');
    const data = stored ? raw : deflateRawSync(raw);
    const nameBuf = Buffer.from(name, 'utf8');
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(stored ? 0 : 8, 8);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(stored ? 0 : 8, 10);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(raw.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt32LE(offset, 42);
    locals.push(local, nameBuf, data);
    centrals.push(central, nameBuf);
    offset += 30 + nameBuf.length + data.length;
  }
  const cd = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(Object.keys(files).length, 8);
  eocd.writeUInt16LE(Object.keys(files).length, 10);
  eocd.writeUInt32LE(cd.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, cd, eocd]);
}

describe('the store reads an uploaded mod for itself', () => {
  it('labels a gameplay mod packed by rsmm (one folder down), whatever its tags say', () => {
    const reasons = modArchiveScopeReasons(
      zip({
        'bloodwolf/manifest.toml':
          '[mod]\nid = "bloodwolf"\ntags = ["hero"]\n\n[[content]]\nkind = "hero"\nid = "X"\n',
        'bloodwolf/assets/EntitySettings/Heroes/Hero_Common/X.entity.ot.EntitySettingsResource.gen':
          'x',
      }),
    );
    expect(reasons).toContain('adds or changes game content (1 [[content]] entries)');
    expect(reasons.some((r) => r.startsWith('overrides game data (EntitySettings/'))).toBe(true);
  });

  it('reads Lua, deflated or stored, at the root too', () => {
    for (const stored of [false, true]) {
      const reasons = modArchiveScopeReasons(
        zip(
          {
            'manifest.toml': '[mod]\nid = "cheat"\n',
            'init.lua': 'local R = require "rsmm"\nR.stat.modify(h, "move_speed", 2)\n',
          },
          stored,
        ),
      );
      expect(reasons).toEqual(['init.lua: calls R.stat.modify']);
    }
  });

  it('passes a client-only mod: a meter with an overlay and its textures', () => {
    const buf = zip({
      'meter/manifest.toml': '[mod]\nid = "meter"\ntags = ["hud"]\n\n[overlay]\ntitle = "DPS"\n',
      'meter/init.lua': 'local R = require "rsmm"\nR.damage.enable()\nR.overlay.publish({})\n',
      'meter/assets/Ui/x.png.Texture.dxt': 'x',
    });
    expect(modArchiveScopeReasons(buf)).toEqual([]);
    expect(modArchiveFiles(buf)).toContainEqual({ path: 'init.lua', text: expect.any(String) });
  });

  it('fails closed on an archive it cannot read', () => {
    expect(modArchiveScopeReasons(Buffer.from('not a zip at all'))).toEqual([
      'the archive is not a zip archive',
    ]);
    const cut = zip({ 'manifest.toml': '[mod]\nid = "a"\n', 'init.lua': 'R.log(1)' });
    // the central directory still lists init.lua, its bytes point past the end
    cut.writeUInt32LE(0x7fffffff, cut.length - 22 - 46 * 1 - 'init.lua'.length + 42);
    expect(modArchiveScopeReasons(cut)).toContain(
      'init.lua cannot be read, so its Lua cannot be checked',
    );
  });
});
