import { describe, expect, it } from 'vitest';
import { modPatchSchema } from '../mod';

describe('editing author credit', () => {
  it('accepts a trimmed credit, explicit removal, or an omitted field', () => {
    expect(modPatchSchema.parse({ author: '  Updated author  ' })).toEqual({
      author: 'Updated author',
    });
    expect(modPatchSchema.parse({ author: null })).toEqual({ author: null });
    expect(modPatchSchema.parse({})).toEqual({});
  });

  it('rejects blank or oversized credits', () => {
    for (const author of ['', '   ', 'a'.repeat(129)]) {
      expect(modPatchSchema.safeParse({ author }).success).toBe(false);
    }
    expect(modPatchSchema.safeParse({ author: 'a'.repeat(128) }).success).toBe(true);
  });

  it('does not allow author credit edits to transfer ownership', () => {
    expect(modPatchSchema.parse({ author: 'Updated', ownerId: 'someone-else' })).toEqual({
      author: 'Updated',
    });
  });
});
