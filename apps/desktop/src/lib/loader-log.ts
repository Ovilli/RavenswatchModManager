/**
 * Parsing for the in-game loader log (`<game>/mods/_log.txt`).
 *
 * A line is `[<ts> <session> <pid>] <msg>`, where `<msg>` may carry a severity
 * token (`[err]`, `[warn]`, from `Loader::log_err` / `log_warn`) and then a
 * bracketed subsystem tag (`[va-gate]`, `[skin-hook]`, `[lua]`). Severity
 * comes FIRST and is separate precisely so `[subsystem]` stays where every
 * existing reader already looks for it.
 *
 * Severity is present only where the loader was taught to emit it, so an
 * untagged line means "not classified", never "fine" — the UI dims nothing on
 * that basis, it only lifts what is tagged. See `Loader::log` in
 * src/loader/src/loader.cpp.
 */

export type LoaderLineKind = 'session' | 'entry' | 'raw';

/** `null` = the loader did not classify this line, NOT "this line is fine". */
export type LoaderSeverity = 'err' | 'warn' | null;

export interface LoaderLogLine {
  kind: LoaderLineKind;
  /** `2026-08-06 21:14:03.881`, or null on a banner / unparsed line. */
  stamp: string | null;
  /** Short per-process session token, so successive injections never blur. */
  session: string | null;
  pid: string | null;
  /** Subsystem tag without brackets (`va-gate`), when the line carries one. */
  tag: string | null;
  /** Severity the loader stamped, when it stamped one. */
  severity: LoaderSeverity;
  /** The human-written part. Whole line for `raw` and `session` kinds. */
  message: string;
  raw: string;
}

const ENTRY = /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) ([0-9a-f]{4}) (\d+)\]\s?(.*)$/;
const TAG = /^\[([a-z0-9][a-z0-9_-]{1,20})\]\s?(.*)$/;
const SEVERITY = /^\[(err|warn)\]\s?(.*)$/;
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
        severity: null,
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
        // A line the loader did not format is usually a crash tail, but
        // guessing a severity from unparsed text would invent signal.
        severity: null,
        message: text,
        raw: text,
      });
      continue;
    }
    let rest = m[4] ?? '';
    const sev = SEVERITY.exec(rest);
    if (sev) rest = sev[2] ?? '';
    const tagged = TAG.exec(rest);
    out.push({
      kind: 'entry',
      stamp: m[1] ?? null,
      session: m[2] ?? null,
      pid: m[3] ?? null,
      tag: tagged?.[1] ?? null,
      severity: (sev?.[1] as LoaderSeverity) ?? null,
      message: tagged ? (tagged[2] ?? '') : rest,
      raw: text,
    });
  }
  return out;
}

/** How many lines the loader flagged. Drives the "N problems" affordance —
 *  the point of severity is that you can find the failure without reading. */
export function loaderLogProblems(lines: LoaderLogLine[]): {
  errors: number;
  warnings: number;
  firstError: LoaderLogLine | null;
} {
  let errors = 0;
  let warnings = 0;
  let firstError: LoaderLogLine | null = null;
  for (const line of lines) {
    if (line.severity === 'err') {
      errors++;
      if (!firstError) firstError = line;
    } else if (line.severity === 'warn') {
      warnings++;
    }
  }
  return { errors, warnings, firstError };
}

/** Distinct subsystem tags present, in first-seen order — the filter list. */
export function loaderLogTags(lines: LoaderLogLine[]): string[] {
  const seen: string[] = [];
  for (const line of lines) {
    if (line.tag && !seen.includes(line.tag)) seen.push(line.tag);
  }
  return seen;
}
