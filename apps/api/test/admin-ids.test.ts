import { describe, expect, it } from 'vitest';
import { parseAdminUserIds } from '../src/admin-ids.js';

describe('parseAdminUserIds', () => {
  it('is empty when unset or blank', () => {
    expect(parseAdminUserIds(undefined)).toEqual([]);
    expect(parseAdminUserIds('  ')).toEqual([]);
  });

  it('accepts one id', () => {
    expect(parseAdminUserIds('abc123')).toEqual(['abc123']);
  });

  it.each([
    ['commas', 'a1,b2,c3'],
    ['commas with spaces', 'a1, b2 , c3'],
    ['semicolons', 'a1;b2;c3'],
    ['spaces', 'a1 b2 c3'],
    ['newlines', 'a1\nb2\r\nc3\n'],
    ['quoted ids', '"a1", "b2", \'c3\''],
    ['a quoted list', '"a1,b2,c3"'],
  ])('splits several admins given with %s', (_label, raw) => {
    expect(parseAdminUserIds(raw)).toEqual(['a1', 'b2', 'c3']);
  });

  it('drops duplicates and empty entries', () => {
    expect(parseAdminUserIds('a1,,a1, ,b2,')).toEqual(['a1', 'b2']);
  });
});
