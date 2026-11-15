import { describe, expect, it } from 'vitest';
import {
  CLIENT_CALLS,
  CLIENT_NAMESPACES,
  isClientOnlyAsset,
  luaReasons,
  manifestReasons,
  modScopeReasons,
} from '../mod-scope';
// The engine's verdicts on shared cases (tests/test_private_only_label.py
// writes this file from src/rsmm/engine/mod_scope.py).
import cases from './fixtures/mod-scope-cases.json';

/** Cases the engine reads as client-only that this copy reads as gameplay.
 *  Allowed: the store's check may only be stricter (it labels; an admin can
 *  clear it). Keep this list short and real. */
const STRICTER: string[] = [];

describe('the store never passes what the engine labels', () => {
  for (const c of cases.lua) {
    it(c.src.replace(/\n/g, ' ⏎ '), () => {
      const gameplay = luaReasons(c.src).length > 0;
      if (c.gameplay) expect(gameplay).toBe(true);
      else if (!STRICTER.includes(c.src)) expect(gameplay).toBe(false);
    });
  }

  it('reads the manifest the same way', () => {
    for (const c of cases.manifest) {
      expect(manifestReasons(c.src).length > 0, c.src).toBe(c.gameplay);
    }
  });

  it('knows the same presentation-only asset families', () => {
    for (const c of cases.asset) {
      const files = [
        { path: 'manifest.toml', text: '[mod]\nid = "a"\n' },
        { path: `assets/${c.path}` },
      ];
      expect(modScopeReasons(files).length === 0, c.path).toBe(c.client_only);
    }
  });

  it('lists the same client-only SDK calls', () => {
    expect([...CLIENT_NAMESPACES].sort()).toEqual(cases.client_namespaces);
    expect([...CLIENT_CALLS].sort()).toEqual(cases.client_calls);
  });
});

describe('it fails closed on what it cannot follow', () => {
  it.each([
    ['local f = load("return require(\\"rsmm\\")")()\nf.give.by_name("x")', 'load'],
    ['local f = loadstring(src)\nf()', 'loadstring'],
    ['dofile("other.lua")', 'dofile'],
    ['local env = getfenv(1)', 'getfenv'],
  ])('%s', (src, needle) => {
    expect(luaReasons(src).join(' ')).toContain(needle);
  });

  it('labels a mod with no manifest, or one it cannot read', () => {
    expect(
      modScopeReasons([{ path: 'init.lua', text: 'local R = require "rsmm"\nR.log(1)' }]),
    ).toContain('has no manifest.toml at its root, so it cannot be checked');
    expect(modScopeReasons([{ path: 'manifest.toml', text: null }])).toContain(
      'manifest.toml cannot be read',
    );
    expect(
      modScopeReasons([
        { path: 'manifest.toml', text: '' },
        { path: 'init.lua', text: null },
      ]),
    ).toContain('init.lua cannot be read, so its Lua cannot be checked');
  });

  it('passes a client-only mod: a HUD, its strings and its textures', () => {
    expect(
      modScopeReasons([
        {
          path: 'manifest.toml',
          text: '[mod]\nid = "meter"\ntags = ["hud"]\n\n[overlay]\ntitle = "x"\n',
        },
        {
          path: 'init.lua',
          text: 'local R = require "rsmm"\nR.damage.enable()\nR.overlay.publish({})',
        },
        { path: 'lang/en.toml' },
        { path: 'assets/Ui/x.png.Texture.dxt' },
      ]),
    ).toEqual([]);
  });

  it('keeps an asset path from posing as presentation', () => {
    expect(isClientOnlyAsset('Text/x.entity.ot.EntitySettingsResource.gen')).toBe(false);
    expect(isClientOnlyAsset('Audio/x.entity.ot')).toBe(false);
  });
});
