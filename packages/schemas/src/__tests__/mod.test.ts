import { describe, it, expect } from 'vitest';
import { modListItemSchema, modVersionSchema } from '../mod';

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
    });
    expect(result.name).toBe('Test Mod');
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
    })).toThrow();
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
