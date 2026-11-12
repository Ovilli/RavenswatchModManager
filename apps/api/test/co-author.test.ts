import { describe, expect, it } from 'vitest';
import { coAuthorQuery, likeExact, pickCoAuthor } from '../src/co-author.js';

const pam = { id: 'u1', name: 'Pam', handle: null };
const ovilli = { id: 'u2', name: 'Ovilli', handle: 'ovilli' };
const otherPam = { id: 'u3', name: 'pam', handle: 'pam2' };

describe('adding a co-author by name or handle', () => {
  it('finds someone with no handle by their display name, ignoring case', () => {
    expect(pickCoAuthor('pam', [pam])).toEqual({ kind: 'found', user: pam });
    expect(pickCoAuthor('  PAM ', [pam])).toEqual({ kind: 'found', user: pam });
  });

  it('accepts a handle with or without @, and a handle beats a name', () => {
    expect(pickCoAuthor('@Ovilli', [ovilli])).toEqual({ kind: 'found', user: ovilli });
    expect(pickCoAuthor('pam2', [pam, otherPam])).toEqual({ kind: 'found', user: otherPam });
  });

  it('takes a user id, exactly, before anything else', () => {
    expect(pickCoAuthor('u3', [pam, otherPam])).toEqual({ kind: 'found', user: otherPam });
    expect(pickCoAuthor(' u1 ', [pam])).toEqual({ kind: 'found', user: pam });
    expect(pickCoAuthor('U1', [pam])).toEqual({ kind: 'none' });
  });

  it('asks for the handle when two people share the name', () => {
    expect(pickCoAuthor('Pam', [pam, otherPam])).toEqual({ kind: 'ambiguous', count: 2 });
  });

  it('reports no match rather than guessing', () => {
    expect(pickCoAuthor('Pa', [pam])).toEqual({ kind: 'none' });
    expect(pickCoAuthor('@', [pam])).toEqual({ kind: 'none' });
  });

  it('compares exactly: LIKE wildcards are escaped', () => {
    expect(coAuthorQuery(' @@x ')).toBe('x');
    expect(likeExact('a_b%c\\d')).toBe('a\\_b\\%c\\\\d');
  });
});
