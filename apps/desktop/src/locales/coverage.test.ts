import { describe, expect, it } from 'vitest';
import { LOCALES, LOCALE_CHOICES } from '../lib/i18n';
import { extractMessages } from './extract';
import { zhCN } from './zh-CN';

const SRC = new URL('..', import.meta.url).pathname;

const CATALOGS: Record<string, Record<string, string> | null> = {
  en: null, // the source language has no catalog by design
  'zh-CN': zhCN,
};

/**
 * The catalogs are keyed by English source string, which is what makes a
 * missing entry invisible at runtime: the message renders in English and
 * nothing complains. These tests are the thing that complains.
 */
describe('translation coverage', () => {
  const messages = extractMessages(SRC);

  it('finds the UI messages in the source tree', () => {
    // A guard against the extractor silently matching nothing (a moved source
    // root, a regex edit) and every coverage test below passing vacuously.
    expect(messages.length).toBeGreaterThan(200);
    expect(messages).toContain('Library');
  });

  it('declares a catalog for every locale', () => {
    for (const locale of LOCALE_CHOICES) {
      expect(Object.keys(CATALOGS)).toContain(locale);
    }
    expect(Object.keys(LOCALES)).toEqual(LOCALE_CHOICES);
  });

  for (const [locale, catalog] of Object.entries(CATALOGS)) {
    if (!catalog) continue;

    it(`${locale} translates every message`, () => {
      const missing = messages.filter((m) => !(m in catalog));
      expect(missing, `${missing.length} message(s) with no ${locale} entry`).toEqual([]);
    });

    it(`${locale} carries no stale entries`, () => {
      const known = new Set(messages);
      const stale = Object.keys(catalog).filter((k) => !known.has(k));
      expect(stale, `${stale.length} ${locale} entry(ies) nothing renders`).toEqual([]);
    });

    it(`${locale} keeps every placeholder`, () => {
      // A dropped `{name}` renders a sentence with a hole in it; an invented
      // one renders a literal `{nmae}` on screen. Both are silent at runtime.
      const wrong: string[] = [];
      for (const [source, translated] of Object.entries(catalog)) {
        const want = [...source.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
        const got = [...translated.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
        if (want.join(',') !== got.join(',')) wrong.push(source);
      }
      expect(wrong, `placeholders differ in ${locale}`).toEqual([]);
    });
  }
});

/**
 * The glossary, enforced.
 *
 * A term that drifts between panels reads as two different features: `profile`
 * rendered 配置 in one place and 方案 in another, next to a mod's own `config`
 * (which IS 配置), is exactly the confusion this table exists to prevent. Each
 * pair says "wherever the English source uses this word, the translation uses
 * that one".
 */
const GLOSSARY: [term: RegExp, zh: string][] = [
  [/\bprofiles?\b/i, '方案'],
  [/\boverlays?\b/i, '悬浮窗'],
  [/\bloader\b/i, '加载器'],
  [/\bvanilla\b/i, '原版'],
  [/\bcollections?\b/i, '合集'],
  [/\bconflicts?\b/i, '冲突'],
  [/\bmods?\b/i, '模组'],
];

/**
 * Strip what is not prose before matching: a `{placeholder}` carries a runtime
 * value (the profile's own name), and a dotted identifier (`manifest.conflicts`)
 * is code quoted verbatim in both languages.
 */
function prose(message: string): string {
  return message.replace(/\{\w+\}/g, ' ').replace(/\b\w+\.\w+\b/g, ' ');
}

describe('zh-CN glossary', () => {
  for (const [term, zh] of GLOSSARY) {
    it(`renders ${term.source} as ${zh}`, () => {
      const drifted = Object.entries(zhCN)
        .filter(([source]) => term.test(prose(source)))
        .filter(([, translated]) => !translated.includes(zh))
        .map(([source]) => source);
      expect(drifted, `${drifted.length} entry(ies) not using ${zh}`).toEqual([]);
    });
  }
});
