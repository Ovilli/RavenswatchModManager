import { beforeEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_LOCALE,
  detectLocale,
  getLocale,
  isLocale,
  normalizeLocale,
  plural,
  setLocale,
  t,
  translate,
} from './i18n';

describe('locale detection', () => {
  it('takes an exact tag', () => {
    expect(detectLocale(['zh-CN'])).toBe('zh-CN');
    expect(detectLocale(['en'])).toBe('en');
  });

  it('matches any Chinese variant to Simplified', () => {
    // Shipping one Chinese catalog and refusing to show it to a zh-TW or
    // zh-Hans user helps nobody — the language row lets them switch back.
    for (const tag of ['zh', 'zh-Hans', 'zh-TW', 'zh-SG', 'ZH-hant']) {
      expect(detectLocale([tag])).toBe('zh-CN');
    }
  });

  it('reads the list in order and ignores what it does not have', () => {
    expect(detectLocale(['fr-FR', 'zh-CN'])).toBe('zh-CN');
    expect(detectLocale(['fr-FR'])).toBe(DEFAULT_LOCALE);
    expect(detectLocale([])).toBe(DEFAULT_LOCALE);
  });

  it('normalizes anything unknown to the default', () => {
    expect(normalizeLocale('zh-CN')).toBe('zh-CN');
    expect(normalizeLocale('kl-GL')).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(undefined)).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(42)).toBe(DEFAULT_LOCALE);
    expect(isLocale('zh-CN')).toBe(true);
    expect(isLocale('zh')).toBe(false);
  });
});

describe('translate', () => {
  it('falls back to the English source when there is no entry', () => {
    expect(translate('zh-CN', 'not a message in any catalog')).toBe(
      'not a message in any catalog',
    );
  });

  it('returns a real translation for a known message', () => {
    expect(translate('zh-CN', 'Settings')).not.toBe('Settings');
    expect(translate('en', 'Settings')).toBe('Settings');
  });

  it('interpolates named placeholders', () => {
    expect(translate('en', 'Install failed: {error}', { error: 'boom' })).toBe(
      'Install failed: boom',
    );
    expect(translate('en', '{n} mods', { n: 3 })).toBe('3 mods');
  });

  it('leaves an unknown placeholder verbatim rather than printing undefined', () => {
    // A translator's typo must be visibly wrong, not quietly wrong.
    expect(translate('en', 'hello {nmae}', { name: 'x' })).toBe('hello {nmae}');
  });
});

describe('the module-level translator', () => {
  beforeEach(() => setLocale('en'));

  it('follows setLocale', () => {
    expect(t('Settings')).toBe('Settings');
    setLocale('zh-CN');
    expect(getLocale()).toBe('zh-CN');
    expect(t('Settings')).not.toBe('Settings');
  });

  it('picks the plural form at the call site and always binds {n}', () => {
    expect(plural(1, '{n} mod', '{n} mods')).toBe('1 mod');
    expect(plural(0, '{n} mod', '{n} mods')).toBe('0 mods');
    expect(plural(7, '{n} mod', '{n} mods')).toBe('7 mods');
  });
});
