import { describe, expect, it } from 'vitest';
import { type Row, parseKv, readOverlayLive, sortRows } from './overlay-state';

/** Build one `R.kv` line the way the Lua SDK writes it. */
const line = (kind: string, key: string, value: string) => `${kind}\t${key}\t${value}`;

describe('parseKv', () => {
  it('reads the three value kinds', () => {
    const text = [
      line('s', 'name', 'Aurora'),
      line('n', 'dealt', '1234.5'),
      line('b', 'is_local', '1'),
      line('b', 'dead', '0'),
    ].join('\n');
    expect(parseKv(text)).toEqual({
      name: 'Aurora',
      dealt: 1234.5,
      is_local: true,
      dead: false,
    });
  });

  it('unescapes keys and string values', () => {
    expect(parseKv(line('s', 'a\\tb', 'one\\ntwo\\\\three'))).toEqual({
      'a\tb': 'one\ntwo\\three',
    });
  });

  it('skips a torn or malformed line instead of failing', () => {
    // The mod rewrites this file while the HUD reads it, so a truncated last
    // line is routine — dropping it beats losing the whole poll.
    const text = [line('s', 'name', 'Aurora'), 's\toverlay.ro', ''].join('\n');
    expect(parseKv(text)).toEqual({ name: 'Aurora' });
  });

  it('ignores an unknown kind and a non-numeric number', () => {
    expect(parseKv([line('x', 'k', 'v'), line('n', 'bad', 'NaN')].join('\n'))).toEqual({});
  });

  it('drops non-finite numbers', () => {
    // Neither is representable in JSON, and on the CLI side `int(nan)` /
    // `int(inf)` raise — one such line used to take `rsmm json overlays` down.
    expect(
      parseKv(
        [
          line('n', 'a', 'NaN'),
          line('n', 'b', 'inf'),
          line('n', 'c', 'Infinity'),
          line('n', 'd', '-Infinity'),
        ].join('\n'),
      ),
    ).toEqual({});
  });

  it('reads CRLF lines', () => {
    // A state file written through a text-mode handle on Windows. Splitting on
    // "\n" alone leaves a trailing \r on the end of every value.
    expect(parseKv(`${line('s', 'name', 'Aurora')}\r\n${line('n', 'v', '2')}\r\n`)).toEqual({
      name: 'Aurora',
      v: 2,
    });
  });

  it('keeps a raw tab inside a value', () => {
    // `parse_kv` splits at the first two tabs only; a four-field line is a
    // value containing a tab, not a malformed record.
    expect(parseKv('s\tk\tone\ttwo')).toEqual({ k: 'one\ttwo' });
  });
});

describe('sortRows', () => {
  const rows = [{ v: 2 }, { v: 10 }, { v: 1 }];

  it('leaves the order alone with no declared sort', () => {
    expect(sortRows(rows, null)).toEqual(rows);
  });

  it('sorts numerically ascending and descending', () => {
    expect(sortRows(rows, { key: 'v', dir: 'asc' }).map((r) => r.v)).toEqual([1, 2, 10]);
    expect(sortRows(rows, { key: 'v', dir: 'desc' }).map((r) => r.v)).toEqual([10, 2, 1]);
  });

  it('puts rows missing the sort key last in either direction', () => {
    const mixed: Row[] = [{ other: 1 }, { v: 5 }, { v: 3 }];
    expect(sortRows(mixed, { key: 'v', dir: 'asc' })).toEqual([{ v: 3 }, { v: 5 }, { other: 1 }]);
    expect(sortRows(mixed, { key: 'v', dir: 'desc' })).toEqual([{ v: 5 }, { v: 3 }, { other: 1 }]);
  });

  it('sorts text rows without throwing on the mixed case', () => {
    const mixed: Row[] = [{ v: 'b' }, { v: 2 }, { v: 'a' }];
    expect(() => sortRows(mixed, { key: 'v', dir: 'asc' })).not.toThrow();
  });
});

describe('readOverlayLive', () => {
  const state = (rows: unknown, extra: string[] = []) =>
    [line('s', 'overlay.rows', JSON.stringify(rows).replace(/\\/g, '\\\\')), ...extra].join('\n');

  it('returns the published rows, sorted', () => {
    const live = readOverlayLive(
      state([
        { label: 'A', dealt: 5 },
        { label: 'B', dealt: 50 },
      ]),
      {
        key: 'dealt',
        dir: 'desc',
      },
    );
    expect(live.exists).toBe(true);
    expect(live.rows.map((r) => r.label)).toEqual(['B', 'A']);
  });

  it('reads meta and the publish timestamp', () => {
    const live = readOverlayLive(
      state(
        [{ label: 'A' }],
        [line('s', 'overlay.meta', '{"run":"3"}'), line('n', 'overlay.updated', '1757000000')],
      ),
    );
    expect(live.meta).toEqual({ run: '3' });
    expect(live.updated).toBe(1757000000);
  });

  it('reports nothing published when the key is absent', () => {
    // A mod using R.kv for its own state is not publishing an overlay.
    const live = readOverlayLive(line('s', 'something.else', 'x'));
    expect(live).toEqual({ rows: [], meta: {}, updated: 0, exists: false });
  });

  it('reports nothing published for malformed JSON', () => {
    expect(readOverlayLive(line('s', 'overlay.rows', '[{')).exists).toBe(false);
  });

  it('drops non-object entries and caps the row count', () => {
    const many = Array.from({ length: 80 }, (_, i) => ({ i }));
    const live = readOverlayLive(state([...many, 'junk', 42]));
    expect(live.rows).toHaveLength(64);
    expect(live.rows[0]).toEqual({ i: 0 });
  });

  it('treats an empty file as nothing published', () => {
    expect(readOverlayLive('').exists).toBe(false);
  });
});
