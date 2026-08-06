import { describe, expect, it } from 'vitest';
import { loaderLogTags, parseLoaderLog } from './loader-log';

const STAMP = '2026-08-06 21:14:03.881';

describe('parseLoaderLog', () => {
  it('splits stamp, session, pid and message', () => {
    const [line] = parseLoaderLog([`[${STAMP} a3f1 12044] loader attached`]);
    expect(line).toEqual({
      kind: 'entry',
      stamp: STAMP,
      session: 'a3f1',
      pid: '12044',
      tag: null,
      message: 'loader attached',
      raw: `[${STAMP} a3f1 12044] loader attached`,
    });
  });

  it('peels the subsystem tag off the message', () => {
    const [line] = parseLoaderLog([`[${STAMP} a3f1 12044] [va-gate] rejected 0x14000000`]);
    expect(line?.tag).toBe('va-gate');
    expect(line?.message).toBe('rejected 0x14000000');
  });

  it('marks session banners so a run boundary is visible', () => {
    const [line] = parseLoaderLog(['== SESSION a3f1 2026-08-06 ==']);
    expect(line?.kind).toBe('session');
    expect(line?.message).toBe('== SESSION a3f1 2026-08-06 ==');
  });

  it('keeps unformatted lines instead of dropping them', () => {
    // A crash tail is exactly the line you need, and it never matches.
    const [line] = parseLoaderLog(['EXCEPTION_ACCESS_VIOLATION at 0x14028f3a0']);
    expect(line?.kind).toBe('raw');
    expect(line?.message).toBe('EXCEPTION_ACCESS_VIOLATION at 0x14028f3a0');
  });

  it('skips blanks and strips the CR from Windows line endings', () => {
    const parsed = parseLoaderLog(['', '   ', `[${STAMP} a3f1 1] hello\r`]);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]?.message).toBe('hello');
    expect(parsed[0]?.raw.endsWith('\r')).toBe(false);
  });

  it('does not mistake a bracketed word in prose for a subsystem tag', () => {
    const [line] = parseLoaderLog([`[${STAMP} a3f1 1] see [_log.txt] for detail`]);
    expect(line?.tag).toBeNull();
    expect(line?.message).toBe('see [_log.txt] for detail');
  });
});

describe('loaderLogTags', () => {
  it('lists distinct tags in first-seen order', () => {
    const parsed = parseLoaderLog([
      `[${STAMP} a3f1 1] [lua] one`,
      `[${STAMP} a3f1 1] [va-gate] two`,
      `[${STAMP} a3f1 1] [lua] three`,
      `[${STAMP} a3f1 1] untagged`,
    ]);
    expect(loaderLogTags(parsed)).toEqual(['lua', 'va-gate']);
  });
});
