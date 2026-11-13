/**
 * Whether a mod changes the game the party plays, decided from what its
 * archive contains: the store's own check behind the "Private games only"
 * label, run on every uploaded version (apps/api scan-service).
 *
 * It mirrors the engine's verdict (`src/rsmm/engine/mod_scope.py`, which
 * `rsmm pack` and `rsmm publish` use), and differs in one direction only: it
 * FAILS CLOSED harder. The engine follows the SDK through a Lua scope walker;
 * this reads Lua with patterns, so anything it cannot follow with certainty is
 * gameplay. It may label a tricky client-only mod (an admin can clear that);
 * it never lets a gameplay mod through unlabelled. Keep CLIENT_NAMESPACES and
 * CLIENT_CALLS equal to the engine's (tests/test_private_only_label.py checks).
 */

/** SDK namespaces whose every member is client-only (engine: CLIENT_NAMESPACES). */
export const CLIENT_NAMESPACES: ReadonlySet<string> = new Set([
  'log',
  'on',
  'off',
  'once',
  'on_match',
  'overlay',
  'exp',
  'kv',
  'config',
  'schedule',
  'health',
  'i18n',
  'damage',
  'camera',
  'audio',
  'input',
]);

/** Single client-only functions inside gameplay namespaces (engine: CLIENT_CALLS). */
export const CLIENT_CALLS: ReadonlySet<string> = new Set([
  'entity.hero',
  'entity.ready',
  'entity.capture_enabled',
  'entity.hp',
  'entity.hp_frac',
  'entity.max_hp',
  'stat.get',
  'stat.cached',
  'stat.keys',
  'stat.names',
  'stat.key',
  'hp.get',
  'hp.frac',
  'hp.max',
  'events.known',
  'events.count',
  'events.category',
  'net.peers',
  'lobby.members',
  'lobby.allies',
  'lobby.hero_name',
  'debug.components',
  'game.get',
  'game.flag',
  'game.cached',
  'game.ready',
  'game.describe',
]);

/** Whether overriding this decoded asset path changes only presentation. */
export function isClientOnlyAsset(decoded: string): boolean {
  const p = decoded.replace(/\\/g, '/');
  const name = p.slice(p.lastIndexOf('/') + 1);
  if (name.endsWith('.Texture.dxt') || name.endsWith('.Texture.nrm')) return true;
  if (p.startsWith('Audio/') && name.endsWith('.bank')) return true;
  return p.startsWith('Text/') && name.endsWith('.LocalText.gen');
}

/** Lua with comments removed; string literals kept (requires live in them). */
function stripComments(src: string): string {
  let out = '';
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i] as string;
    if (c === "'" || c === '"') {
      let j = i + 1;
      while (j < n && src[j] !== c) j += src[j] === '\\' ? 2 : 1;
      out += src.slice(i, j + 1);
      i = j + 1;
    } else if (src.startsWith('--', i)) {
      const m = /^--\[(=*)\[/.exec(src.slice(i, i + 64));
      if (m) {
        const end = src.indexOf(`]${m[1]}]`, i + m[0].length);
        i = end < 0 ? n : end + (m[1] as string).length + 2;
      } else {
        const nl = src.indexOf('\n', i);
        i = nl < 0 ? n : nl;
      }
    } else if (c === '[' && /^\[(=*)\[/.test(src.slice(i, i + 64))) {
      const m = /^\[(=*)\[/.exec(src.slice(i, i + 64)) as RegExpExecArray;
      const end = src.indexOf(`]${m[1]}]`, i + m[0].length);
      const stop = end < 0 ? n : end + (m[1] as string).length + 2;
      out += src.slice(i, stop);
      i = stop;
    } else {
      out += c;
      i += 1;
    }
  }
  return out;
}

/** String literals replaced with "" so text is never read as code. */
function blankStrings(src: string): string {
  return src
    .replace(/\[(=*)\[[\s\S]*?\]\1\]/g, '""')
    .replace(/'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g, '""');
}

const IDENT = '[A-Za-z_]\\w*';
/** A global read: not a field (`t.x`, `t:x`) and not a table key (`{ x = 1 }`
 *  is still matched; the store over-labels rather than under-labels). */
const GLOBAL_PREFIX = '(?<![\\w.:])';

/** Globals that reach the SDK, or code, without naming it. */
const UNFOLLOWABLE: Record<string, string> = {
  _G: 'the global table (_G)',
  _ENV: 'the environment table (_ENV)',
  package: 'the module cache (package)',
  load: 'load (runs code built at run time)',
  loadstring: 'loadstring (runs code built at run time)',
  dofile: 'dofile (runs another file)',
  loadfile: 'loadfile (runs another file)',
  getfenv: 'getfenv (the environment table)',
  setfenv: 'setfenv (the environment table)',
  rawget: 'rawget (reads a table past its checks)',
};

/** Why this Lua source changes the game; empty when it is client-only. */
export function luaReasons(src: string): string[] {
  const reasons = new Set<string>();
  const kept = stripComments(src);
  const aliases = new Set<string>(['R']);

  // How the SDK is obtained. The one form that can be followed is a binding
  // that ends its statement: `[local] NAME = require "rsmm"` / `require("rsmm")`.
  const requireRe = /(?<![\w.:])require\s*(\(\s*)?(?:(["'])((?:\\.|(?!\2).)*)\2|(\[=*\[))?/g;
  // Where the string literals are: a `require` written inside one is text.
  const spans: [number, number][] = [];
  for (const s of kept.matchAll(/\[(=*)\[[\s\S]*?\]\1\]|'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g)) {
    spans.push([s.index ?? 0, (s.index ?? 0) + s[0].length]);
  }
  const inString = (at: number) => spans.some(([a, b]) => at > a && at < b);
  for (const m of kept.matchAll(requireRe)) {
    if (inString(m.index ?? 0)) continue;
    const arg = m[3];
    // The string must be the whole argument: `require("rs" .. "mm")` builds
    // the name at run time, and reading "rs" alone let it through.
    const end = (m.index ?? 0) + m[0].length;
    const whole = m[1]
      ? /^\s*\)\s*(?!\.\.|[[.:("'])/.test(kept.slice(end, end + 8))
      : /^\s*(?!\.\.|[[.:("'])/.test(kept.slice(end, end + 8));
    if (arg === undefined || !whole || !/^[\w.-]+$/.test(arg)) {
      reasons.add(
        'uses require with something other than a plain string, so what it loads cannot be checked',
      );
      continue;
    }
    if (arg.startsWith('rsmm.')) {
      reasons.add(`requires the SDK internal "${arg}"`);
      continue;
    }
    if (arg !== 'rsmm') continue;
    const at = m.index ?? 0;
    const before = kept.slice(Math.max(0, at - 80), at);
    const after = kept.slice(at + m[0].length, at + m[0].length + 40);
    // A statement starts after `;`, a line break, `)` or a block keyword.
    const start = '(?:^|[;\\n)]|\\b(?:do|then|else|repeat|end)\\s)';
    const bound = new RegExp(`${start}\\s*(?:local\\s+)?(${IDENT})\\s*=\\s*$`).exec(before);
    const closes = /^\s*(?:\)\s*)?(?:;|\n|$|(?:local|end|return|if|for|while|do|function)\b)/.test(
      after,
    );
    const bare = new RegExp(`${start}\\s*$`).test(before);
    if (bare && closes) continue; // a bare `require "rsmm"` binds nothing
    if (!bound || !closes) {
      reasons.add(
        'stores the SDK somewhere other than a plain local (`local R = require "rsmm"`), so its use cannot be checked',
      );
      continue;
    }
    const name = bound[1] as string;
    if (name === '_ENV') {
      reasons.add('makes the SDK its environment (_ENV), so its use cannot be checked');
      continue;
    }
    aliases.add(name);
  }

  const code = blankStrings(kept);
  for (const [name, what] of Object.entries(UNFOLLOWABLE)) {
    if (new RegExp(`${GLOBAL_PREFIX}${name}\\b`).test(code)) {
      reasons.add(`reaches ${what}, which can hold the SDK under a name that cannot be checked`);
    }
  }
  if (!aliases.has('rsmm') && new RegExp(`${GLOBAL_PREFIX}rsmm\\b`).test(code)) {
    reasons.add('uses the native loader bindings (rsmm.*)');
  }

  for (const alias of aliases) {
    const ref = new RegExp(
      `${GLOBAL_PREFIX}${alias}\\b((?:\\s*\\.\\s*${IDENT})*)(\\s*[\\[:]?)`,
      'g',
    );
    for (const m of code.matchAll(ref)) {
      const chain = (m[1] ?? '')
        .split('.')
        .map((p) => p.trim())
        .filter(Boolean);
      const tail = (m[2] ?? '').trim();
      if (tail === '[' || tail === ':') {
        reasons.add(`accesses the SDK dynamically (${alias}${tail}...)`);
        continue;
      }
      if (chain.length === 0) {
        const at = m.index ?? 0;
        const before = code.slice(Math.max(0, at - 40), at);
        const after = code.slice(at + m[0].length, at + m[0].length + 30);
        if (new RegExp(`local\\s+${alias}\\s*$`).test(before) || /^\s*=\s*require\b/.test(after)) {
          continue; // the alias's own declaration
        }
        reasons.add(`passes the SDK table (${alias}) around, so its use cannot be checked`);
        continue;
      }
      const [ns, fn] = chain as [string, string | undefined];
      if (CLIENT_NAMESPACES.has(ns)) continue;
      if (fn !== undefined && CLIENT_CALLS.has(`${ns}.${fn}`)) continue;
      reasons.add(`calls ${alias}.${chain.slice(0, 2).join('.')}`);
    }
  }
  return [...reasons].sort();
}

/** Why a manifest.toml changes the game: `[[content]]` or `[[patch]]` blocks
 *  (or those keys written any other TOML way, at the top level). */
export function manifestReasons(text: string): string[] {
  const reasons: string[] = [];
  let content = 0;
  let patch = 0;
  let topLevel = true;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    const header = /^\[\[?\s*["']?([A-Za-z_][\w-]*)["']?\s*[\].]/.exec(line);
    if (header) {
      topLevel = false;
      if (header[1] === 'content') content += 1;
      if (header[1] === 'patch') patch += 1;
      continue;
    }
    if (topLevel) {
      const key = /^["']?(content|patch)["']?\s*[=.]/.exec(line);
      if (key?.[1] === 'content') content += 1;
      if (key?.[1] === 'patch') patch += 1;
    }
  }
  if (content) reasons.push(`adds or changes game content (${content} [[content]] entries)`);
  if (patch) reasons.push(`patches game data (${patch} [[patch]] entries)`);
  return reasons;
}

/** One file of a mod: its path inside the mod folder, and (for manifest.toml
 *  and Lua) its text, or null when it could not be read. */
export interface ModFile {
  path: string;
  text?: string | null;
}

/** Why this mod changes the game; empty when it is client-only. Every reason
 *  is reported so an author can see what to change. */
export function modScopeReasons(files: readonly ModFile[]): string[] {
  const reasons = new Set<string>();
  const manifest = files.find((f) => f.path === 'manifest.toml');
  if (!manifest) reasons.add('has no manifest.toml at its root, so it cannot be checked');
  else if (manifest.text == null) reasons.add('manifest.toml cannot be read');
  else for (const r of manifestReasons(manifest.text)) reasons.add(r);

  for (const f of files) {
    const p = f.path.replace(/\\/g, '/');
    if (p.toLowerCase().endsWith('.lua')) {
      if (f.text == null) reasons.add(`${p} cannot be read, so its Lua cannot be checked`);
      else for (const r of luaReasons(f.text)) reasons.add(`${p}: ${r}`);
    }
    if (p.startsWith('_root/')) reasons.add('replaces game-root files (_root/)');
    if (p.startsWith('assets/')) {
      const rel = p.slice('assets/'.length);
      if (rel.startsWith('_root/')) reasons.add(`replaces a game-root file (${rel.slice(6)})`);
      else if (rel && !isClientOnlyAsset(rel)) reasons.add(`overrides game data (${rel})`);
    }
  }
  return [...reasons].sort();
}
