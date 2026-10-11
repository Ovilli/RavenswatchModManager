import { describe, expect, it } from 'vitest';
import { firstSightOfDeepLink } from './desktop-auth';

function memoryStorage(): Pick<Storage, 'getItem' | 'setItem'> {
  const m = new Map<string, string>();
  return {
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => {
      m.set(k, v);
    },
  };
}

describe('firstSightOfDeepLink', () => {
  const link = 'rsmm://desktop-auth?token=abc&app=nonce-1';

  it('lets a link through once, then refuses it for the rest of the window', () => {
    // The reload after a successful sign-in gets the same link back from the
    // plugin's getCurrent(); handling it again reported a bogus failure.
    const storage = memoryStorage();
    expect(firstSightOfDeepLink(link, storage)).toBe(true);
    expect(firstSightOfDeepLink(link, storage)).toBe(false);
  });

  it('still lets a NEW sign-in through', () => {
    const storage = memoryStorage();
    firstSightOfDeepLink(link, storage);
    expect(firstSightOfDeepLink('rsmm://desktop-auth?token=def&app=nonce-2', storage)).toBe(true);
  });

  it('does not block a sign-in over an unreadable record', () => {
    const storage = memoryStorage();
    storage.setItem('rsmm.desktopAuthHandledLinks', '{not json');
    expect(firstSightOfDeepLink(link, storage)).toBe(true);
  });
});
