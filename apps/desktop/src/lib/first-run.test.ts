import { beforeEach, describe, expect, it } from 'vitest';
import {
  ackDisclosure,
  changelogSeen,
  disclosureAck,
  hasRunBefore,
  markChangelogSeen,
} from './first-run';

describe('first-run state', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('starts with no disclosure acknowledgement and no changelog mark', () => {
    expect(disclosureAck()).toBeNull();
    expect(changelogSeen()).toBeNull();
  });

  it('records the acknowledged revision, not a bare flag', () => {
    ackDisclosure('1');
    expect(disclosureAck()).toBe('1');
    // A bumped revision must not read as already-acknowledged.
    expect(disclosureAck()).not.toBe('2');
  });

  it('round-trips the changelog mark', () => {
    markChangelogSeen('5.0.2');
    expect(changelogSeen()).toBe('5.0.2');
  });

  it('detects a returning install from the persisted store key', () => {
    expect(hasRunBefore()).toBe(false);
    localStorage.setItem('rsmm-grimoire', '{"state":{}}');
    expect(hasRunBefore()).toBe(true);
  });

  it('survives a storage that throws', () => {
    const original = localStorage.setItem;
    localStorage.setItem = () => {
      throw new Error('QuotaExceededError');
    };
    expect(() => markChangelogSeen('5.0.2')).not.toThrow();
    localStorage.setItem = original;
  });
});
