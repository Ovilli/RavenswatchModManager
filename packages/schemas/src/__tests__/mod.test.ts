import { describe, it, expect } from 'vitest';
import {
  modListItemSchema,
  modManifestSchema,
  modVersionCreateSchema,
  modVersionSchema,
} from '../mod';

describe('modListItemSchema', () => {
  it('validates a correct mod list item', () => {
    const result = modListItemSchema.parse({
      id: '550e8400-e29b-41d4-a716-446655440000',
      slug: 'test-mod',
      name: 'Test Mod',
      author: 'author',
      summary: 'A test mod',
      license: 'MIT',
      latestVersion: '1.0.0',
      downloads: 100,
      updatedAt: new Date().toISOString(),
      category: 'gameplay',
      imageUrl: 'https://example.com/cover.png',
      rating: 4.5,
      tags: ['fun', 'wip'],
    });
    expect(result.name).toBe('Test Mod');
    expect(result.tags).toEqual(['fun', 'wip']);
  });

  it('accepts nullable optional fields', () => {
    const result = modListItemSchema.parse({
      id: '550e8400-e29b-41d4-a716-446655440000',
      slug: 'test-mod',
      name: 'Test Mod',
      author: null,
      summary: null,
      license: null,
      latestVersion: null,
      downloads: 0,
      updatedAt: new Date().toISOString(),
      category: null,
      imageUrl: null,
      rating: null,
      tags: [],
    });
    expect(result.category).toBeNull();
  });

  it('rejects missing required fields', () => {
    expect(() => modListItemSchema.parse({})).toThrow();
  });

  it('rejects invalid uuid', () => {
    expect(() => modListItemSchema.parse({
      id: 'not-a-uuid',
      slug: 'test',
      name: 'Test',
      downloads: 0,
      updatedAt: new Date().toISOString(),
      tags: [],
    })).toThrow();
  });
});

describe('modManifestSchema compat fields', () => {
  const base = { id: 'my-mod', name: 'My Mod', version: '1.0.0' };

  it('accepts optional compat metadata', () => {
    const m = modManifestSchema.parse({
      ...base,
      sdk_version: '>=3.0,<4',
      game_build: '1.2.0',
      min_loader: '0.1.11',
    });
    expect(m.sdk_version).toBe('>=3.0,<4');
    expect(m.game_build).toBe('1.2.0');
    expect(m.min_loader).toBe('0.1.11');
  });

  it('stays valid without compat fields (older manifests)', () => {
    const m = modManifestSchema.parse(base);
    expect(m.sdk_version).toBeUndefined();
    expect(m.game_build).toBeUndefined();
  });

  it('accepts dependency version ranges (not just exact pins)', () => {
    const m = modManifestSchema.parse({
      ...base,
      dependencies: { core: '>=1.2 <2.0', loot: '^1.0', ui: '1.2.x', any: '*' },
    });
    expect(m.dependencies?.core).toBe('>=1.2 <2.0');
    expect(m.dependencies?.any).toBe('*');
  });
});

describe('modListItemSchema compat fields', () => {
  it('surfaces nullable compat hints', () => {
    const r = modListItemSchema.parse({
      id: '550e8400-e29b-41d4-a716-446655440000',
      slug: 'my-mod',
      name: 'M',
      author: null,
      summary: null,
      license: null,
      latestVersion: null,
      downloads: 0,
      updatedAt: new Date().toISOString(),
      category: null,
      imageUrl: null,
      rating: null,
      tags: [],
      sdkVersion: '>=3.0,<4',
      gameBuild: null,
    });
    expect(r.sdkVersion).toBe('>=3.0,<4');
    expect(r.gameBuild).toBeNull();
  });
});

describe('modVersionSchema', () => {
  it('validates a correct mod version', () => {
    const result = modVersionSchema.parse({
      id: '550e8400-e29b-41d4-a716-446655440000',
      modId: '550e8400-e29b-41d4-a716-446655440001',
      version: '1.0.0',
      sha256: 'a'.repeat(64),
      sizeBytes: 1024,
      manifestJson: { id: 'test-mod', name: 'Test', version: '1.0.0' },
      assetUrl: 'https://example.com/mod.zip',
      createdAt: new Date().toISOString(),
    });
    expect(result.version).toBe('1.0.0');
  });

  it('rejects invalid semver', () => {
    expect(() => modVersionSchema.parse({
      id: '550e8400-e29b-41d4-a716-446655440000',
      modId: '550e8400-e29b-41d4-a716-446655440001',
      version: 'not-valid',
      sizeBytes: 1024,
      manifestJson: { id: 'test-mod', name: 'Test', version: '1.0.0' },
      assetUrl: 'https://example.com/mod.zip',
      createdAt: new Date().toISOString(),
    })).toThrow();
  });

  it('rejects invalid sha256 length', () => {
    expect(() => modVersionSchema.parse({
      id: '550e8400-e29b-41d4-a716-446655440000',
      modId: '550e8400-e29b-41d4-a716-446655440001',
      version: '1.0.0',
      sha256: 'too-short',
      sizeBytes: 1024,
      manifestJson: { id: 'test-mod', name: 'Test', version: '1.0.0' },
      assetUrl: 'https://example.com/mod.zip',
      createdAt: new Date().toISOString(),
    })).toThrow();
  });
});

describe('modVersionCreateSchema', () => {
  const manifest = { id: 'damage-meter', name: 'Damage Meter', version: '1.2.3' };
  const base = {
    version: '1.2.3',
    sha256: 'a'.repeat(64),
    sizeBytes: 16447,
    manifest,
  };

  it('accepts a row whose version matches the packed manifest', () => {
    expect(modVersionCreateSchema.parse(base).version).toBe('1.2.3');
  });

  it('rejects a row labelled differently from the manifest inside it', () => {
    // The damage-meter case (2026-08-24): published as 1.2.3 with a manifest
    // that still said 1.2.2. Nothing errored — the client installed it, the
    // files landed, the manifest read 1.2.2, and the library went on offering
    // the same update forever. Pressing it changed nothing, which reads as a
    // broken app rather than a mislabelled artifact.
    const bad = { ...base, manifest: { ...manifest, version: '1.2.2' } };
    const res = modVersionCreateSchema.safeParse(bad);
    expect(res.success).toBe(false);
    if (!res.success) {
      expect(res.error.issues[0]?.message).toMatch(/match the version inside the packed manifest/);
      expect(res.error.issues[0]?.path).toEqual(['version']);
    }
  });
});
