import { describe, expect, it } from 'vitest';
import { type LogChunk, appendChunk, emptyTail, sessionSlice } from './loader-log-tail';

const chunk = (over: Partial<LogChunk> = {}): LogChunk => ({
  exists: true,
  size: 0,
  offset: 0,
  content: '',
  reset: false,
  truncatedHead: false,
  ...over,
});

describe('appendChunk', () => {
  it('appends complete lines and carries the resume offset', () => {
    const a = appendChunk(emptyTail, chunk({ content: 'one\ntwo\n', offset: 8 }), 100);
    expect(a.lines).toEqual(['one', 'two']);
    expect(a.offset).toBe(8);
    const b = appendChunk(a, chunk({ content: 'three\n', offset: 14 }), 100);
    expect(b.lines).toEqual(['one', 'two', 'three']);
    expect(b.offset).toBe(14);
  });

  it('an empty poll changes nothing but the offset', () => {
    const a = appendChunk(emptyTail, chunk({ content: 'one\n', offset: 4 }), 100);
    const b = appendChunk(a, chunk({ content: '', offset: 4 }), 100);
    expect(b.lines).toEqual(['one']);
  });

  it('REPLACES the buffer on a rotation instead of splicing two runs', () => {
    const a = appendChunk(emptyTail, chunk({ content: 'old\n', offset: 4 }), 100);
    const b = appendChunk(a, chunk({ content: 'new\n', offset: 4, reset: true }), 100);
    expect(b.lines).toEqual(['new']);
    // The old run's lines are gone, so the buffer is no longer "truncated".
    expect(b.truncated).toBe(false);
  });

  it('caps the buffer by dropping the OLDEST lines', () => {
    const a = appendChunk(emptyTail, chunk({ content: 'a\nb\nc\nd\n', offset: 8 }), 2);
    expect(a.lines).toEqual(['c', 'd']);
    expect(a.truncated).toBe(true);
  });

  it('a vanished file empties the buffer rather than freezing stale lines', () => {
    const a = appendChunk(emptyTail, chunk({ content: 'one\n', offset: 4 }), 100);
    const b = appendChunk(a, chunk({ exists: false }), 100);
    expect(b.lines).toEqual([]);
    expect(b.offset).toBeNull();
  });
});

describe('sessionSlice', () => {
  const lines = ['== SESSION aaa ==', 'old', '== SESSION bbb ==', 'new'];

  it('keeps only the newest session by default', () => {
    expect(sessionSlice(lines, false)).toEqual(['== SESSION bbb ==', 'new']);
  });

  it('keeps everything when asked', () => {
    expect(sessionSlice(lines, true)).toEqual(lines);
  });

  it('passes through a log with no banner at all', () => {
    expect(sessionSlice(['a', 'b'], false)).toEqual(['a', 'b']);
  });
});
