import { describe, expect, it } from 'vitest';
import {
  DEFAULT_FONT,
  DEFAULT_FONT_SCALE,
  FONT_CHOICES,
  FONT_PRESETS,
  MAX_FONT_SCALE,
  MIN_FONT_SCALE,
  applyAppearance,
  normalizeFont,
  normalizeFontScale,
} from './appearance';

describe('font normalization', () => {
  it('accepts every advertised preset', () => {
    for (const choice of FONT_CHOICES) {
      expect(normalizeFont(choice)).toBe(choice);
    }
  });

  it('falls back to the default for anything unknown', () => {
    for (const bad of ['comic-sans', '', null, undefined, 42, {}]) {
      expect(normalizeFont(bad)).toBe(DEFAULT_FONT);
    }
  });
});

describe('font scale normalization', () => {
  it('clamps to the supported range', () => {
    expect(normalizeFontScale(10)).toBe(MIN_FONT_SCALE);
    expect(normalizeFontScale(9000)).toBe(MAX_FONT_SCALE);
    expect(normalizeFontScale(120)).toBe(120);
  });

  it('rounds and coerces numeric strings (range inputs hand back strings)', () => {
    expect(normalizeFontScale('115')).toBe(115);
    expect(normalizeFontScale(112.4)).toBe(112);
  });

  it('falls back to 100 rather than shrinking the UI to nothing', () => {
    for (const bad of [Number.NaN, undefined, null, 'huge', {}]) {
      expect(normalizeFontScale(bad)).toBe(DEFAULT_FONT_SCALE);
    }
  });
});

/** Minimal stand-in for <html>. The suite runs in plain node (no jsdom),
 * and `applyAppearance` only ever touches these two surfaces. */
function fakeRoot() {
  const vars: Record<string, string> = {};
  const dataset: Record<string, string> = {};
  const el = {
    style: {
      setProperty: (k: string, v: string) => {
        vars[k] = v;
      },
    },
    dataset,
  };
  return { el: el as unknown as HTMLElement, vars, dataset };
}

describe('applyAppearance', () => {
  it('writes density as an attribute the stylesheet keys off', () => {
    const { el, dataset } = fakeRoot();
    applyAppearance({ density: 'compact' }, el);
    expect(dataset.density).toBe('compact');
    applyAppearance({ density: 'nonsense' }, el);
    expect(dataset.density).toBe('cozy');
    applyAppearance({}, el);
    expect(dataset.density).toBe('cozy');
  });

  it('writes every typography var plus the scale', () => {
    const { el, vars, dataset } = fakeRoot();
    applyAppearance({ fontFamily: 'sans', fontScale: 125 }, el);
    expect(vars['--font-body']).toBe(FONT_PRESETS.sans.vars.body);
    expect(vars['--font-display']).toBe(FONT_PRESETS.sans.vars.display);
    expect(vars['--font-accent']).toBe(FONT_PRESETS.sans.vars.accent);
    expect(vars['--font-mono']).toBe(FONT_PRESETS.sans.vars.mono);
    expect(vars['--ui-scale']).toBe('125%');
    expect(dataset.font).toBe('sans');
  });

  it('sanitizes stored garbage instead of emitting invalid CSS', () => {
    const { el, vars } = fakeRoot();
    applyAppearance({ fontFamily: 'nope', fontScale: -5 }, el);
    expect(vars['--font-body']).toBe(FONT_PRESETS[DEFAULT_FONT].vars.body);
    expect(vars['--ui-scale']).toBe(`${MIN_FONT_SCALE}%`);
  });

  it('is a no-op without a document (SSR / node import)', () => {
    expect(() => applyAppearance({ fontFamily: 'sans', fontScale: 110 }, null)).not.toThrow();
  });
});
