/**
 * Parsing for the in-game loader log (`<game>/mods/_log.txt`).
 *
 * The loader has no severity levels — every line is
 * `[<ts> <session> <pid>] <msg>`, optionally prefixed with a bracketed
 * subsystem tag (`[va-gate]`, `[skin-hook]`, `[lua]`). See `Loader::log` in
 * src/loader/src/loader.cpp. So there is nothing to colour by severity; the
 * useful split is stamp / subsystem / message, plus the `== SESSION ... ==`
 * banners that separate one game launch from the next.
 */

export type LoaderLineKind = 'session' | 'entry' | 'raw';

export interface LoaderLogLine {
  kind: LoaderLineKind;
  /** `2026-08-06 21:14:03.881`, or null on a banner / unparsed line. */
  stamp: string | null;
  /** Short per-process session token, so successive injections never blur. */
  session: string | null;
  pid: string | null;
  /** Subsystem tag without brackets (`va-gate`), when the line carries one. */
  tag: string | null;
  /** The human-written part. Whole line for `raw` and `session` kinds. */
  message: string;
  raw: string;
}

const ENTRY = /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) ([0-9a-f]{4}) (\d+)\]\s?(.*)$/;
const TAG = /^\[([a-z0-9][a-z0-9_-]{1,20})\]\s?(.*)$/;
const SESSION_MARK = '== SESSION ';

export function parseLoaderLog(lines: string[]): LoaderLogLine[] {
  const out: LoaderLogLine[] = [];
  for (const raw of lines) {
    const text = raw.replace(/\r$/, '');
    if (!text.trim()) continue;
    if (text.includes(SESSION_MARK)) {
      out.push({
        kind: 'session',
        stamp: null,
        session: null,
        pid: null,
        tag: null,
        message: text.trim(),
        raw: text,
      });
      continue;
    }
    const m = ENTRY.exec(text);
    if (!m) {
      // Anything the loader didn't format — a crash dump tail, a stray
      // engine write. Keep it: in a diagnostic log the unparseable line is
      // often the one that matters.
      out.push({
        kind: 'raw',
        stamp: null,
        session: null,
        pid: null,
        tag: null,
        message: text,
        raw: text,
      });
      continue;
    }
    const rest = m[4] ?? '';
    const tagged = TAG.exec(rest);
    out.push({
      kind: 'entry',
      stamp: m[1] ?? null,
      session: m[2] ?? null,
      pid: m[3] ?? null,
      tag: tagged?.[1] ?? null,
      message: tagged ? (tagged[2] ?? '') : rest,
      raw: text,
    });
  }
  return out;
}

/** Distinct subsystem tags present, in first-seen order — the filter list. */
export function loaderLogTags(lines: LoaderLogLine[]): string[] {
  const seen: string[] = [];
  for (const line of lines) {
    if (line.tag && !seen.includes(line.tag)) seen.push(line.tag);
  }
  return seen;
}
