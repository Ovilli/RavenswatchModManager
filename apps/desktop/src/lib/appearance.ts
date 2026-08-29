/**
 * Typeface + UI-scale presets.
 *
 * The stylesheet (`@rsmm/ui/styles.css`) routes every `font-family` through
 * four CSS vars and sizes the root element from `--ui-scale`, so switching a
 * preset here restyles the whole app without touching a component. Nothing
 * else is allowed to set those vars — this is the single writer.
 */

import { LOCALES, type Locale, msg, normalizeLocale } from './i18n';

export type FontChoice = 'grimoire' | 'serif' | 'sans' | 'mono';

interface FontPreset {
  /** English source; Settings renders it through `t()`. */
  label: string;
  hint: string;
  /** CSS var overrides written onto <html>. */
  vars: {
    body: string;
    display: string;
    accent: string;
    mono: string;
  };
}

const SYSTEM_SANS =
  'Inter, "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';
const SYSTEM_SERIF = 'Georgia, "Times New Roman", "Liberation Serif", serif';
const SYSTEM_MONO = '"JetBrains Mono", ui-monospace, "Cascadia Mono", Consolas, monospace';

/**
 * Appended to every font var while a CJK language is active.
 *
 * None of the grimoire faces carry Han glyphs, and a browser falling back on
 * its own picks a different face per var — headings in one font, body in
 * another, both unrelated to the preset. Naming the fallbacks keeps the CJK
 * text coherent (and picks the system UI face on each platform) while Latin
 * text still renders in the chosen preset, because the preset fonts come
 * first and only the glyphs they lack fall through.
 */
const CJK_FALLBACK =
  '"Noto Sans SC", "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", "WenQuanYi Micro Hei", sans-serif';

export const FONT_PRESETS: Record<FontChoice, FontPreset> = {
  grimoire: {
    label: msg('Grimoire'),
    hint: msg('Blackletter headings, Garamond body — the default look.'),
    vars: {
      body: "'EB Garamond', Georgia, serif",
      display: "'UnifrakturCook', 'UnifrakturMaguntia', serif",
      accent: "'Cormorant Garamond', Georgia, serif",
      mono: SYSTEM_MONO,
    },
  },
  serif: {
    label: msg('Plain serif'),
    hint: msg('Same shape, no blackletter. Easier on long reading.'),
    vars: {
      body: SYSTEM_SERIF,
      display: SYSTEM_SERIF,
      accent: SYSTEM_SERIF,
      mono: SYSTEM_MONO,
    },
  },
  sans: {
    label: msg('System sans'),
    hint: msg('Maximum legibility — your OS UI font everywhere.'),
    vars: {
      body: SYSTEM_SANS,
      display: SYSTEM_SANS,
      accent: SYSTEM_SANS,
      mono: SYSTEM_MONO,
    },
  },
  mono: {
    label: msg('Monospace'),
    hint: msg('Everything in JetBrains Mono. For the terminal-minded.'),
    vars: {
      body: SYSTEM_MONO,
      display: SYSTEM_MONO,
      accent: SYSTEM_MONO,
      mono: SYSTEM_MONO,
    },
  },
};

export const FONT_CHOICES = Object.keys(FONT_PRESETS) as FontChoice[];

export const DEFAULT_FONT: FontChoice = 'grimoire';
export const DEFAULT_FONT_SCALE = 100;
export const MIN_FONT_SCALE = 80;
export const MAX_FONT_SCALE = 150;

export function normalizeFont(value: unknown): FontChoice {
  return typeof value === 'string' && value in FONT_PRESETS ? (value as FontChoice) : DEFAULT_FONT;
}

/** Clamp to the supported range and round to whole percent. Anything
 * unparseable (a hand-edited localStorage blob, an older build's payload)
 * falls back to 100 rather than shrinking the UI to nothing. */
export function normalizeFontScale(value: unknown): number {
  // `Number(null)` and `Number('')` are 0, which would clamp to the minimum
  // and silently shrink the UI — only real numbers and numeric strings count.
  if (typeof value !== 'number' && (typeof value !== 'string' || value.trim() === '')) {
    return DEFAULT_FONT_SCALE;
  }
  const n = Number(value);
  if (!Number.isFinite(n)) return DEFAULT_FONT_SCALE;
  return Math.min(MAX_FONT_SCALE, Math.max(MIN_FONT_SCALE, Math.round(n)));
}

/**
 * Whether the UI animates.
 *
 * Written as `data-motion` on <html>; the stylesheet collapses every animation
 * and transition duration under `[data-motion='reduced']`. Durations rather
 * than `animation: none`, because a few entrances animate opacity from 0 and
 * killing the animation outright can strand an element invisible.
 *
 * The OS `prefers-reduced-motion` block in the stylesheet is left alone and
 * still wins on its own: this switch can turn animation OFF for someone whose
 * system never asked, and it deliberately cannot turn it back ON for someone
 * whose system did.
 */
export const DEFAULT_ANIMATIONS = true;

export function normalizeAnimations(value: unknown): boolean {
  // Only an explicit `false` disables. An older build's payload has no such
  // key at all, and `undefined` must read as the default rather than as off.
  return value === false ? false : DEFAULT_ANIMATIONS;
}

export type Density = 'cozy' | 'compact';

export const DEFAULT_DENSITY: Density = 'cozy';

export function normalizeDensity(value: unknown): Density {
  return value === 'compact' ? 'compact' : DEFAULT_DENSITY;
}

/** Suffix a preset stack with the CJK faces, for a CJK UI language. */
function withCjk(stack: string, locale: Locale): string {
  return LOCALES[locale].cjk ? `${stack}, ${CJK_FALLBACK}` : stack;
}

export function applyAppearance(
  settings: {
    fontFamily?: unknown;
    fontScale?: unknown;
    density?: unknown;
    animations?: unknown;
    language?: unknown;
  },
  root: HTMLElement | null = typeof document === 'undefined' ? null : document.documentElement,
): void {
  if (!root) return;
  const font = normalizeFont(settings.fontFamily);
  const scale = normalizeFontScale(settings.fontScale);
  const locale = normalizeLocale(settings.language);
  const { vars } = FONT_PRESETS[font];
  root.style.setProperty('--font-body', withCjk(vars.body, locale));
  root.style.setProperty('--font-display', withCjk(vars.display, locale));
  root.style.setProperty('--font-accent', withCjk(vars.accent, locale));
  root.style.setProperty('--font-mono', withCjk(vars.mono, locale));
  // `lang` drives the browser's own line-breaking and font selection for CJK,
  // and is what a screen reader switches voice on.
  root.lang = LOCALES[locale].tag;
  root.style.setProperty('--ui-scale', `${scale}%`);
  root.dataset.font = font;
  // Density is a CSS-only switch: the stylesheet keys padding overrides off
  // this attribute. Until now the setting was stored and read by nobody.
  root.dataset.density = normalizeDensity(settings.density);
  root.dataset.motion = normalizeAnimations(settings.animations) ? 'full' : 'reduced';
}
