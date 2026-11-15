import { describe, expect, it } from 'vitest';
import { hasPrivateOnlyTag, setPrivateOnlyTag } from '../private-only';

describe('Private games only labels', () => {
  it('recognizes canonical and legacy labels without classifying unrelated mods', () => {
    for (const tag of [
      'private-only',
      'Private only',
      'Private games only',
      'private-games-only',
      ' CHEAT ',
      'Cheats',
    ]) {
      expect(hasPrivateOnlyTag([tag])).toBe(true);
    }
    for (const tags of [null, undefined, [], ['gameplay', 'cheat-sheet', 'balance']]) {
      expect(hasPrivateOnlyTag(tags)).toBe(false);
    }
  });

  it('normalizes duplicate aliases and removes only protected labels for admin removal', () => {
    const tags = ['camera', ' CHEAT ', 'private-only', 'qol', 'Cheats'];
    expect(setPrivateOnlyTag(tags, true)).toEqual(['camera', 'qol', 'private-only']);
    expect(setPrivateOnlyTag(tags, false)).toEqual(['camera', 'qol']);
  });
});
