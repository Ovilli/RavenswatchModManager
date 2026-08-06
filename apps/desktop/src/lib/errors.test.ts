import { describe, expect, it } from 'vitest';
import { explainError } from './errors';

describe('explainError', () => {
  it('recognises a missing CLI and points at the install step', () => {
    const { title, hint } = explainError('RSMM CLI not found.\n\nThe desktop app needs…');
    expect(title).toMatch(/command-line tool/i);
    expect(hint).toMatch(/pip install/);
  });

  it('recognises a timeout', () => {
    expect(explainError('rsmm json build timed out after 600000ms').title).toMatch(/too long/i);
  });

  it('recognises an unreadable reply', () => {
    expect(explainError('rsmm json list returned invalid JSON: <!doctype').title).toMatch(
      /could not read/i,
    );
  });

  it('recognises a missing game install', () => {
    expect(explainError('rsmm json apply failed (exit 1): game dir not found').title).toMatch(
      /Ravenswatch install/i,
    );
  });

  it('recognises a permissions failure on either platform wording', () => {
    expect(explainError('PermissionError: permission denied').title).toMatch(/not allowed/i);
    expect(explainError('Access is denied.').title).toMatch(/not allowed/i);
  });

  it('falls back to a neutral headline and no hint', () => {
    expect(explainError('rsmm json apply failed (exit 2): kaboom')).toEqual({
      title: 'The command did not finish.',
      hint: null,
    });
  });
});
