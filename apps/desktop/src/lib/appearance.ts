/**
 * Typeface + UI-scale presets.
 *
 * The stylesheet (`@rsmm/ui/styles.css`) routes every `font-family` through
 * four CSS vars and sizes the root element from `--ui-scale`, so switching a
 * preset here restyles the whole app without touching a component. Nothing
 * else is allowed to set those vars — this is the single writer.
 */

export type FontChoice = 'grimoire' | 'serif' | 'sans' | 'mono';

interface FontPreset {
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

export const FONT_PRESETS: Record<FontChoice, FontPreset> = {
  grimoire: {
    label: 'Grimoire',
    hint: 'Blackletter headings, Garamond body — the default look.',
    vars: {
      body: "'EB Garamond', Georgia, serif",
      display: "'UnifrakturCook', 'UnifrakturMaguntia', serif",
      accent: "'Cormorant Garamond', Georgia, serif",
      mono: SYSTEM_MONO,
    },
  },
  serif: {
    label: 'Plain serif',
    hint: 'Same shape, no blackletter. Easier on long reading.',
    vars: {
      body: SYSTEM_SERIF,
      display: SYSTEM_SERIF,
      accent: SYSTEM_SERIF,
      mono: SYSTEM_MONO,
    },
  },
  sans: {
    label: 'System sans',
    hint: 'Maximum legibility — your OS UI font everywhere.',
    vars: {
      body: SYSTEM_SANS,
      display: SYSTEM_SANS,
      accent: SYSTEM_SANS,
      mono: SYSTEM_MONO,
    },
  },
  mono: {
    label: 'Monospace',
    hint: 'Everything in JetBrains Mono. For the terminal-minded.',
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

export type Density = 'cozy' | 'compact';

export const DEFAULT_DENSITY: Density = 'cozy';

export function normalizeDensity(value: unknown): Density {
  return value === 'compact' ? 'compact' : DEFAULT_DENSITY;
}

export function applyAppearance(
  settings: { fontFamily?: unknown; fontScale?: unknown; density?: unknown },
  root: HTMLElement | null = typeof document === 'undefined' ? null : document.documentElement,
): void {
  if (!root) return;
  const font = normalizeFont(settings.fontFamily);
  const scale = normalizeFontScale(settings.fontScale);
  const { vars } = FONT_PRESETS[font];
  root.style.setProperty('--font-body', vars.body);
  root.style.setProperty('--font-display', vars.display);
  root.style.setProperty('--font-accent', vars.accent);
  root.style.setProperty('--font-mono', vars.mono);
  root.style.setProperty('--ui-scale', `${scale}%`);
  root.dataset.font = font;
  // Density is a CSS-only switch: the stylesheet keys padding overrides off
  // this attribute. Until now the setting was stored and read by nobody.
  root.dataset.density = normalizeDensity(settings.density);
}
