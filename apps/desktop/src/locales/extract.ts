/**
 * Pull every translatable message out of the source tree.
 *
 * The catalogs are keyed by the English source string, so the extractor is
 * what keeps them honest: `coverage.test.ts` compares this list against each
 * catalog and fails on a missing entry (a string that would silently render in
 * English) or a stale one (a message nobody asks for any more).
 *
 * Deliberately a regex rather than a parse: the four call shapes below are the
 * whole contract, they are enforced by review, and a TypeScript parser here
 * would be a build dependency for a test that reads files.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

/** A single- or double-quoted TS string literal, escapes included. */
const STR = String.raw`'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"`;

/** `t.n(count, one, other)` — both plural forms are separate catalog entries. */
const PLURAL_RE = new RegExp(String.raw`\bt\.n\(\s*[^,]+?,\s*(${STR})\s*,\s*(${STR})`, 'g');

/** `t('…')`, `tr('…')` (the module-level translator) and `msg('…')`. */
const SINGLE_RE = new RegExp(String.raw`\b(?:t|tr|msg)\(\s*(${STR})`, 'g');

/** Directories that hold no UI strings of their own. */
const SKIP_DIRS = new Set(['node_modules', 'locales', 'assets', 'icons']);

function unquote(literal: string): string {
  const body = literal.slice(1, -1);
  // Only the escapes the codebase actually uses. A `\n` in a message is real
  // (the quit prompt), and `\'` / `\"` appear wherever a quote is inside.
  return body
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\(['"\\])/g, '$1');
}

export function extractFromSource(source: string): string[] {
  const out: string[] = [];
  for (const m of source.matchAll(PLURAL_RE)) {
    if (m[1]) out.push(unquote(m[1]));
    if (m[2]) out.push(unquote(m[2]));
  }
  for (const m of source.matchAll(SINGLE_RE)) {
    if (m[1]) out.push(unquote(m[1]));
  }
  return out;
}

function walk(dir: string, files: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, files);
      continue;
    }
    // Tests hold their own fixture strings; translating those would put test
    // data in the shipped catalogs.
    if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry)) continue;
    files.push(full);
  }
  return files;
}

/** Every message the app can render, sorted and de-duplicated. */
export function extractMessages(root: string): string[] {
  const seen = new Set<string>();
  for (const file of walk(root)) {
    for (const message of extractFromSource(readFileSync(file, 'utf8'))) seen.add(message);
  }
  return [...seen].sort();
}
