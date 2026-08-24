import { describe, expect, it } from 'vitest';
import { formatBytes, parseProgressLine } from './rsmm';

// The CLI writes progress as NDJSON on STDERR, because stdout is contractually
// a single JSON object — the bridge's whole output contract. So the parser has
// to pick progress lines out of a stream that also carries real diagnostics.
describe('parseProgressLine', () => {
  it('reads a progress line', () => {
    const p = parseProgressLine('{"progress": {"phase": "download", "received": 1024, "total": 6000}}');
    expect(p).toEqual({ phase: 'download', received: 1024, total: 6000 });
  });

  it('accepts an unknown total (no Content-Length)', () => {
    // Rendered as indeterminate by the caller; 0 must not become "0%".
    expect(parseProgressLine('{"progress":{"phase":"download","received":10,"total":0}}')).toEqual({
      phase: 'download',
      received: 10,
      total: 0,
    });
  });

  it('ignores ordinary stderr diagnostics', () => {
    for (const line of [
      '',
      'note: the loader planted in the game dir is not the build this one carries',
      '  [warn] failed to clear something',
      'Traceback (most recent call last):',
    ]) {
      expect(parseProgressLine(line)).toBeNull();
    }
  });

  it('ignores JSON that is not progress, and malformed JSON', () => {
    expect(parseProgressLine('{"ok": true, "status": "updated"}')).toBeNull();
    expect(parseProgressLine('{"progress": {"received": "lots"}}')).toBeNull();
    expect(parseProgressLine('{"progress": {truncated')).toBeNull();
  });
});

describe('formatBytes', () => {
  it('scales to a readable unit', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1_629_738)).toBe('1.6 MB');
    expect(formatBytes(5_796_120)).toBe('5.5 MB');
  });

  it('does not render nonsense for a bad number', () => {
    expect(formatBytes(Number.NaN)).toBe('0 B');
    expect(formatBytes(-1)).toBe('0 B');
  });
});
