/**
 * Decode a mod's live overlay rows from its state file.
 *
 * The HUD used to get these already-decoded, by spawning the Python CLI once a
 * second per open overlay while the game was being played. The declaration
 * (title, columns, sort) is static for the session, so only the rows need
 * following — and following a file is a read, not a process. The Rust side
 * hands over the raw bytes (`read_overlay_state`); this turns them into the
 * same shape `rsmm json overlays` returns, so the HUD renders one record type
 * whichever path it came from.
 *
 * This is the THIRD implementation of the same `R.kv` line format: the Lua SDK
 * writes it, `src/rsmm/cli/cmd_overlay.py` reads it, and now so does this. The
 * decoders must agree — `parse_kv` / `_unescape` there are the reference,
 * and `sortRows` mirrors `_sorted_rows`.
 *
 * Pure and DOM-free on purpose: the desktop suite has no jsdom, and the parser
 * is the part worth testing.
 */

/** Matches `MAX_ROWS` in `cmd_overlay.py` — a HUD that long stops being one. */
export const MAX_ROWS = 64;

export type Cell = string | number | boolean;
export type Row = Record<string, Cell>;

/** Undo the SDK's line escaping (`rsmm.lua`'s `_unesc`). */
function unesc(s: string): string {
  let out = '';
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    if (c === '\\' && i + 1 < s.length) {
      const next = s[i + 1];
      out += next === '\\' ? '\\' : next === 'n' ? '\n' : next === 't' ? '\t' : next;
      i += 1;
      continue;
    }
    out += c;
  }
  return out;
}

/**
 * Parse the `<type>\t<key>\t<value>` store `R.kv` writes.
 *
 * A line without at least two tabs is skipped rather than failing the parse:
 * the mod rewrites this file while the HUD is reading it, so a torn last line
 * is normal and the next tick is 1s away.
 */
export function parseKv(text: string): Record<string, Cell> {
  const out: Record<string, Cell> = {};
  // `\r?\n` and a two-tab split, matching `parse_kv`'s `splitlines()` and
  // `split("\t", 2)`. Both matter: a state file written through a text-mode
  // handle on Windows arrives with CRLF, which a plain `\n` split leaves on
  // the end of every value, and a raw tab inside a value must stay part of it
  // rather than turning the line into four fields and getting dropped.
  for (const line of text.split(/\r?\n/)) {
    const firstTab = line.indexOf('\t');
    if (firstTab < 0) continue;
    const secondTab = line.indexOf('\t', firstTab + 1);
    if (secondTab < 0) continue;
    const kind = line.slice(0, firstTab);
    const value = line.slice(secondTab + 1);
    const key = unesc(line.slice(firstTab + 1, secondTab));
    if (kind === 's') {
      out[key] = unesc(value);
    } else if (kind === 'n') {
      const n = Number(value);
      // `isFinite`, not `!isNaN`: JS reads "Infinity" as a number and Python's
      // `float()` reads "inf" as one. Neither is representable in JSON, and on
      // the CLI side `int(inf)` raises, so both decoders drop them.
      if (Number.isFinite(n)) out[key] = n;
    } else if (kind === 'b') {
      out[key] = value === '1';
    }
  }
  return out;
}

export interface OverlaySort {
  key: string;
  dir: 'asc' | 'desc';
}

/**
 * Order rows by the mod's declared sort.
 *
 * Rows missing the sort key go last in EITHER direction rather than being
 * compared as a number against a string — mirroring `_sorted_rows`, where the
 * same choice keeps a half-published row from throwing.
 */
export function sortRows(rows: Row[], sort?: OverlaySort | null): Row[] {
  if (!sort) return rows;
  const { key } = sort;
  const reverse = sort.dir === 'desc';
  const rank = (row: Row): [number, number | string] => {
    const v = row[key];
    if (v === undefined || typeof v === 'boolean') return [1, 0];
    if (typeof v === 'number') return [0, reverse ? -v : v];
    return [0, String(v)];
  };
  // Decorate rather than compare inside the sort: `rank` is called once per
  // row instead of once per comparison, and the tuple keeps the
  // missing-key group pinned to the end.
  return rows
    .map((row) => ({ row, key: rank(row) }))
    .sort((a, b) => {
      if (a.key[0] !== b.key[0]) return a.key[0] - b.key[0];
      const [, l] = a.key;
      const [, r] = b.key;
      if (typeof l === 'number' && typeof r === 'number') return l - r;
      return String(l).localeCompare(String(r));
    })
    .map((d) => d.row);
}

export interface OverlayLive {
  rows: Row[];
  meta: Record<string, Cell>;
  /** Unix seconds of the mod's last publish; 0 = never. */
  updated: number;
  /** false = nothing has been published yet this session. */
  exists: boolean;
}

const EMPTY: OverlayLive = { rows: [], meta: {}, updated: 0, exists: false };

function asRows(raw: unknown): Row[] | null {
  if (!Array.isArray(raw)) return null;
  return raw.filter((r): r is Row => typeof r === 'object' && r !== null && !Array.isArray(r));
}

function parseJson(raw: Cell | undefined): unknown {
  if (typeof raw !== 'string') return undefined;
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}

/**
 * `{rows, meta, updated, exists}` from a state file's raw text.
 *
 * `exists` follows the CLI's meaning — the mod has published rows — not merely
 * "the file is there". A state file with other keys but no `overlay.rows` is
 * a mod using `R.kv` for something else, which is not an overlay publish.
 */
export function readOverlayLive(text: string, sort?: OverlaySort | null): OverlayLive {
  const kv = parseKv(text);
  const rows = asRows(parseJson(kv['overlay.rows']));
  if (!rows) return EMPTY;
  const meta = parseJson(kv['overlay.meta']);
  const updated = kv['overlay.updated'];
  return {
    rows: sortRows(rows.slice(0, MAX_ROWS), sort),
    meta:
      typeof meta === 'object' && meta !== null && !Array.isArray(meta)
        ? (meta as Record<string, Cell>)
        : {},
    updated: typeof updated === 'number' ? Math.trunc(updated) : 0,
    exists: true,
  };
}
