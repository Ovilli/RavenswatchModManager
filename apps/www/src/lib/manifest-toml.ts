/**
 * Read the `[mod]` table of a mod's `manifest.toml`, for pre-filling the
 * publish form.
 *
 * Deliberately NOT a general TOML parser: it understands exactly the value
 * shapes a `[mod]` table uses (strings in all four quote styles, string
 * arrays, booleans, numbers) and ignores everything else. It never throws — a
 * manifest it cannot read yields fewer fields, and the form is simply filled in
 * by hand as before. The server still validates whatever the form submits, so
 * this is a convenience, not a trust boundary.
 */

export interface ModMeta {
  id?: string;
  name?: string;
  version?: string;
  author?: string;
  summary?: string;
  description?: string;
  license?: string;
  tags?: string[];
  repoUrl?: string;
  homepageUrl?: string;
}

const KEY_RE = /^([A-Za-z0-9_-]+)\s*=\s*(.*)$/;
// `[table]` and `[[array-of-tables]]` both end the previous table — real manifests
// are full of `[[content]]` / `[[patch]]` blocks with their own `id` and `name`.
const TABLE_RE = /^\[\[?([^[\]]+)\]\]?\s*(?:#.*)?$/;
const STRING_RE = /"((?:[^"\\]|\\.)*)"|'([^']*)'/g;

const ESCAPES: Record<string, string> = {
  b: '\b',
  t: '\t',
  n: '\n',
  f: '\f',
  r: '\r',
  '"': '"',
  '\\': '\\',
};

function unescapeBasic(s: string): string {
  return s.replace(/\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)/g, (_, c: string) => {
    if (c.length > 1) return String.fromCodePoint(Number.parseInt(c.slice(1), 16));
    return ESCAPES[c] ?? c;
  });
}

type Value = string | boolean | number | string[] | undefined;

/** Index of the closing unescaped `"` in `s` (which starts AFTER the opening one). */
function closingQuote(s: string): number {
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '\\') i++;
    else if (s[i] === '"') return i;
  }
  return -1;
}

function parseValue(first: string, nextLine: () => string | undefined): Value {
  const s = first.trim();

  if (s.startsWith('"""') || s.startsWith("'''")) {
    const q = s.slice(0, 3);
    let body = s.slice(3);
    let out = '';
    for (;;) {
      const end = body.indexOf(q);
      if (end >= 0) {
        out += body.slice(0, end);
        break;
      }
      out += `${body}\n`;
      const nl = nextLine();
      if (nl === undefined) break;
      body = nl;
    }
    // A newline right after the opening delimiter is not part of the value.
    const trimmed = out.startsWith('\n') ? out.slice(1) : out;
    return q === '"""' ? unescapeBasic(trimmed) : trimmed;
  }

  if (s.startsWith('"')) {
    const end = closingQuote(s.slice(1));
    return end < 0 ? undefined : unescapeBasic(s.slice(1, 1 + end));
  }
  if (s.startsWith("'")) {
    const end = s.indexOf("'", 1);
    return end < 0 ? undefined : s.slice(1, end);
  }

  if (s.startsWith('[')) {
    // Collect lines until the brackets balance, skipping strings and comments.
    let text = s;
    for (;;) {
      let depth = 0;
      let inStr: string | null = null;
      let clean = '';
      for (let i = 0; i < text.length; i++) {
        const c = text[i] as string;
        if (inStr) {
          clean += c;
          if (c === '\\' && inStr === '"') clean += text[++i] ?? '';
          else if (c === inStr) inStr = null;
        } else if (c === '#') {
          while (i < text.length && text[i] !== '\n') i++;
          clean += '\n';
        } else {
          if (c === '"' || c === "'") inStr = c;
          if (c === '[') depth++;
          if (c === ']') depth--;
          clean += c;
        }
      }
      if (depth <= 0) {
        const items: string[] = [];
        for (const m of clean.matchAll(STRING_RE)) {
          items.push(m[1] !== undefined ? unescapeBasic(m[1]) : (m[2] ?? ''));
        }
        return items;
      }
      const nl = nextLine();
      if (nl === undefined) return undefined;
      text += `\n${nl}`;
    }
  }

  const bare = s.replace(/\s+#.*$/, '').trim();
  if (bare === 'true') return true;
  if (bare === 'false') return false;
  if (/^[+-]?\d[\d_]*(\.\d+)?$/.test(bare)) return Number(bare.replace(/_/g, ''));
  return undefined;
}

/** Every `key = value` the manifest's `[mod]` table carries, by raw key. */
function modTable(text: string): Record<string, Value> {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/);
  const out: Record<string, Value> = {};
  let table = '';
  let i = 0;
  const nextLine = () => (i < lines.length ? lines[i++] : undefined);
  while (i < lines.length) {
    const line = (lines[i++] as string).trim();
    if (line === '' || line.startsWith('#')) continue;
    const header = TABLE_RE.exec(line);
    if (header) {
      table = (header[1] as string).trim();
      continue;
    }
    const kv = KEY_RE.exec(line);
    if (!kv) continue;
    // Multi-line values must be consumed even outside `[mod]`, so their inner
    // lines are never mistaken for keys or table headers.
    const value = parseValue(kv[2] as string, nextLine);
    if (table === 'mod') out[kv[1] as string] = value;
  }
  return out;
}

const str = (v: Value): string | undefined =>
  typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined;

export function parseModManifest(text: string): ModMeta {
  let t: Record<string, Value>;
  try {
    t = modTable(text);
  } catch {
    return {};
  }
  const tags = Array.isArray(t.tags)
    ? t.tags.map((x) => x.trim()).filter((x) => x !== '')
    : undefined;
  const meta: ModMeta = {
    id: str(t.id),
    name: str(t.name),
    version: str(t.version),
    author: str(t.author),
    summary: str(t.summary),
    description: str(t.description),
    license: str(t.license),
    tags: tags && tags.length > 0 ? tags : undefined,
    repoUrl: str(t.repo_url) ?? str(t.repository),
    homepageUrl: str(t.homepage_url) ?? str(t.homepage),
  };
  for (const k of Object.keys(meta) as (keyof ModMeta)[]) {
    if (meta[k] === undefined) delete meta[k];
  }
  return meta;
}
