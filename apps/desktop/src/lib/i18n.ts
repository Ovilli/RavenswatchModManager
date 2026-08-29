/**
 * UI translation.
 *
 * The message *is* the key: `t('Install')` looks up the English source string
 * in the active locale's catalog and returns the English one back when there is
 * no entry. That is deliberate for a retrofit of an app that was written
 * English-only — a component that has not been migrated yet still renders, and
 * a translation that falls behind a copy change degrades to English rather than
 * to a raw `settings.paths.title` key on screen.
 *
 * The upkeep cost of that choice (a reworded English string silently orphans
 * its translation) is paid by `locales/coverage.test.ts`, which extracts every
 * `t(...)` literal from the source tree and fails when the catalog is missing
 * an entry or carries one nothing uses any more.
 *
 * Two entry points, both mandatory:
 *
 *  - `useT()` inside a component. It subscribes to the language setting, so
 *    switching languages re-renders the app with no reload.
 *  - `t()` at module scope / inside plain functions (toasts, error mappers).
 *    It reads the module-level locale that `setLocale` keeps in sync with the
 *    store.
 *
 * Never build a sentence by concatenation — a translator cannot reorder the
 * pieces. Use `{name}` placeholders and pass `vars`.
 */

import { zhCN } from '../locales/zh-CN';

export type Locale = 'en' | 'zh-CN';

export interface LocaleMeta {
  /** Name of the language *in* that language — what a speaker looks for. */
  native: string;
  /** Name in English, for the settings row's secondary line. */
  english: string;
  /** `lang` attribute + `Intl` locale for dates and numbers. */
  tag: string;
  /** CJK locales need a font stack the grimoire faces cannot supply. */
  cjk?: boolean;
}

export const LOCALES: Record<Locale, LocaleMeta> = {
  en: { native: 'English', english: 'English', tag: 'en' },
  'zh-CN': { native: '简体中文', english: 'Chinese (Simplified)', tag: 'zh-CN', cjk: true },
};

export const LOCALE_CHOICES = Object.keys(LOCALES) as Locale[];

export const DEFAULT_LOCALE: Locale = 'en';

export type Catalog = Record<string, string>;

const CATALOGS: Record<Locale, Catalog | null> = {
  en: null, // English is the source; a catalog would be an identity map.
  'zh-CN': zhCN,
};

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && value in LOCALES;
}

export function normalizeLocale(value: unknown): Locale {
  return isLocale(value) ? value : DEFAULT_LOCALE;
}

/**
 * Best locale for a fresh install, from the browser/OS languages.
 *
 * Matched on the primary subtag so `zh`, `zh-Hans`, `zh-TW` and `zh-SG` all
 * land on Simplified Chinese: shipping one Chinese catalog and refusing to show
 * it to a `zh-TW` user helps nobody, and the language row lets them switch.
 */
export function detectLocale(
  languages: readonly string[] = typeof navigator === 'undefined'
    ? []
    : (navigator.languages ?? [navigator.language]),
): Locale {
  for (const raw of languages) {
    if (typeof raw !== 'string') continue;
    const tag = raw.toLowerCase();
    if (isLocale(raw)) return raw;
    if (tag.startsWith('zh')) return 'zh-CN';
    if (tag.startsWith('en')) return 'en';
  }
  return DEFAULT_LOCALE;
}

export type Vars = Record<string, string | number>;

const PLACEHOLDER = /\{(\w+)\}/g;

function interpolate(text: string, vars: Vars | undefined): string {
  if (!vars) return text;
  // An unknown placeholder is left verbatim rather than replaced with
  // "undefined": a translator who typos `{cnt}` should produce visibly wrong
  // text, not text that reads fine and lies.
  return text.replace(PLACEHOLDER, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

export function translate(locale: Locale, message: string, vars?: Vars): string {
  const catalog = CATALOGS[locale];
  const hit = catalog ? catalog[message] : undefined;
  return interpolate(hit && hit.length > 0 ? hit : message, vars);
}

let current: Locale = DEFAULT_LOCALE;

/** Single writer: the store's language subscription (see `main.tsx`). */
export function setLocale(locale: Locale): void {
  current = normalizeLocale(locale);
}

export function getLocale(): Locale {
  return current;
}

/**
 * Translate outside React. Components must use `useT()` instead — this reads a
 * module-level value and so does not re-render anything when it changes.
 */
export function t(message: string, vars?: Vars): string {
  return translate(current, message, vars);
}

/**
 * English pluralisation, resolved at the call site.
 *
 * Both forms are separate catalog entries, which is what lets a language with
 * one form (Chinese) translate them to the same string and a language with two
 * translate them differently. `{n}` is always available.
 */
export function plural(count: number, one: string, other: string, vars?: Vars): string {
  return t(count === 1 ? one : other, { n: count, ...vars });
}

/** `Intl` locale tag for the active language — for dates, numbers, sorting. */
export function localeTag(locale: Locale = current): string {
  return LOCALES[locale].tag;
}

/**
 * Mark a string for translation without translating it here.
 *
 * For messages that must be declared at module scope — a nav table, a list of
 * settings tabs — where there is no locale yet and no component to re-render.
 * The declaration carries the English source (and gets picked up by the
 * extractor); the render site passes it through `t()`.
 */
export function msg(message: string): string {
  return message;
}
