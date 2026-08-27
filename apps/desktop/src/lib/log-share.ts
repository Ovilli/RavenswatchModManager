import { LOG_SHARE_MAX_CHARS, type LogShareSource } from '@rsmm/schemas';
import { loaderLogProblems, parseLoaderLog } from './loader-log';
import type { LocalMod } from './rsmm';

/**
 * Build the text that a "Share log" upload actually publishes.
 *
 * Two jobs, in this order, and the order is the point:
 *
 *  1. **Redact.** A loader log is written on the user's machine and quotes
 *     their filesystem, so it carries their Windows account name in every
 *     absolute path — and, once the lobby-attribute parser is armed, the
 *     gamertags of everyone in their co-op session. A share is a public,
 *     unlisted URL that the user is about to hand to a stranger in a support
 *     thread; publishing those unasked is not something a checkbox default
 *     should decide, so redaction is on by default and the dialog shows the
 *     exact bytes before anything leaves the machine.
 *  2. **Clamp.** The API caps the stored text. A log is truncated from the
 *     FRONT, never the back: the crash is on the last line, so dropping the
 *     tail throws away the only part anyone asked for.
 */

const REDACTED_USER = '<user>';

/** Windows (`C:\Users\alice`, `C:/Users/alice`) and bare `\Users\alice`. */
const WIN_USER = /((?:[A-Za-z]:)?[\\/]Users[\\/])([^\\/\r\n"'<>|:*?]+)/g;
/** Linux/macOS home directories. */
const NIX_USER = /(\/home\/|\/Users\/)([^/\s:"'\r\n]+)/g;
const EMAIL = /\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b/g;
/** Steam64 ids all start with the same 7 digits and are exactly 17 long. */
const STEAM_ID = /\b7656119\d{10}\b/g;
/** Dotted quad. A four-segment VERSION string is the same token and gets
 *  blanked too — the shapes are indistinguishable, and blanking a version
 *  reads oddly where leaking a peer's address does real harm. Five-segment
 *  tokens are excluded by the lookaround so a build stamp survives. */
const IPV4 = /(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(?![\w.])/g;
/** Loopback / unspecified / broadcast carry no identity, and blanking them
 *  destroys the one thing a networking bug report needs to say. */
const IP_KEEP = new Set(['127.0.0.1', '0.0.0.0', '255.255.255.255', 'localhost']);
/** `PlayerName=Alice`, `gamertag: "Bob"`, `player = Carol` — the shapes the
 *  lobby-attribute parser and the damage meter write. */
const NAME_KV =
  /\b(player_?name|playername|gamertag|display_?name|steam_?name)(\s*[=:]\s*)("?)([^"\s,;)\]}]+)\3/gi;
/** Anything that looks like a credential, regardless of what wrote it. */
const SECRET_KV =
  /\b(token|secret|api_?key|password|session_?id|auth)(\s*[=:]\s*)("?)([^"\s,;)\]}]+)\3/gi;
const BEARER = /\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*/g;

/**
 * Scrub personally identifying detail out of one block of log text.
 *
 * Deliberately conservative about what it blanks: every replacement keeps the
 * surrounding structure (the key, the path prefix, the quoting) so a redacted
 * line still reads as the same event. A redaction that turns a path into
 * `<redacted>` makes the log useless for the person trying to help.
 */
export function redactLogText(text: string): string {
  return text
    .replace(EMAIL, '<email>')
    .replace(BEARER, 'Bearer <redacted>')
    .replace(SECRET_KV, (_m, key, sep, quote) => `${key}${sep}${quote}<redacted>${quote}`)
    .replace(NAME_KV, (_m, key, sep, quote) => `${key}${sep}${quote}<player>${quote}`)
    .replace(STEAM_ID, '<steamid>')
    .replace(IPV4, (m) => (IP_KEEP.has(m) ? m : '<ip>'))
    .replace(WIN_USER, (_m, prefix) => `${prefix}${REDACTED_USER}`)
    .replace(NIX_USER, (_m, prefix) => `${prefix}${REDACTED_USER}`);
}

export interface LogReportInput {
  rsmmVersion: string;
  os: string;
  /** Loader log lines, oldest first, as `readLoaderLog` returns them. */
  loaderLines: string[];
  /** Path the loader log was read from (redacted like everything else). */
  loaderPath?: string | null;
  /** Raw launcher (desktop app) log, newest lines last. Optional. */
  launcherLog?: string | null;
  mods?: LocalMod[];
  gameBuild?: string | null;
  loaderVersion?: string | null;
  /** What the user typed to describe the problem. */
  note?: string;
  redact?: boolean;
}

export interface LogReport {
  content: string;
  source: LogShareSource;
  /** Set when the log was longer than the API accepts and the oldest lines
   *  were dropped — the dialog says so rather than letting it pass silently. */
  truncated: boolean;
  meta: Record<string, unknown>;
}

function modSummary(mods: LocalMod[]): string[] {
  if (mods.length === 0) return ['mods: none installed'];
  const enabled = mods.filter((m) => m.enabled).length;
  return [
    `mods: ${enabled} enabled / ${mods.length} installed`,
    ...mods
      .slice()
      .sort((a, b) => a.id.localeCompare(b.id))
      .map((m) => `  [${m.enabled ? 'on ' : 'off'}] ${m.id} ${m.version}`),
  ];
}

/**
 * Assemble the header + logs into the single text blob that gets uploaded.
 *
 * The header exists because a log on its own answers "what happened" and never
 * "to what" — the first question in every support thread is which app version,
 * which OS and which mods were on, and a share that omits them just moves the
 * back-and-forth to a different page.
 */
export function buildLogReport(input: LogReportInput): LogReport {
  const redact = input.redact !== false;
  const scrub = (s: string) => (redact ? redactLogText(s) : s);

  const header: string[] = [
    '=== RSMM diagnostic report ===',
    `generated: ${new Date().toISOString()}`,
    `rsmm: ${input.rsmmVersion}`,
    `os: ${input.os}`,
  ];
  if (input.gameBuild) header.push(`game build: ${input.gameBuild}`);
  if (input.loaderVersion) header.push(`loader: ${input.loaderVersion}`);
  if (input.loaderPath) header.push(`log path: ${scrub(input.loaderPath)}`);
  header.push(`redacted: ${redact ? 'yes' : 'no'}`);
  if (input.mods) header.push(...modSummary(input.mods));

  // Triage line. The whole reason the loader stamps severity is that a reader
  // should not have to scan a thousand lines to find the failure — a shared
  // log that buries it has given that back.
  const problems = loaderLogProblems(parseLoaderLog(input.loaderLines));
  if (problems.errors || problems.warnings) {
    header.push(`flagged: ${problems.errors} error(s), ${problems.warnings} warning(s)`);
    if (problems.firstError) {
      header.push(`first error: ${scrub(problems.firstError.raw)}`);
    }
  }
  if (input.note?.trim()) {
    header.push('', '--- what the reporter said ---', scrub(input.note.trim()));
  }

  const loader = scrub(input.loaderLines.join('\n'));
  const launcher = input.launcherLog?.trim() ? scrub(input.launcherLog.trim()) : '';

  const sections = [
    header.join('\n'),
    `--- loader log (${input.loaderLines.length} lines) ---`,
    loader || '(empty)',
  ];
  if (launcher) sections.push('--- launcher log ---', launcher);

  const full = `${sections.join('\n\n')}\n`;
  const { content, truncated } = clampReport(full, header.join('\n'));

  return {
    content,
    source: launcher ? 'bundle' : 'loader',
    truncated,
    meta: {
      modCount: input.mods?.length ?? null,
      enabledMods: input.mods?.filter((m) => m.enabled).map((m) => `${m.id}@${m.version}`) ?? null,
      gameBuild: input.gameBuild ?? null,
      loaderVersion: input.loaderVersion ?? null,
      redacted: redact,
      truncated,
      errors: problems.errors,
      warnings: problems.warnings,
    },
  };
}

/**
 * Fit the report under the API's limit by dropping the OLDEST log lines.
 *
 * The header is always kept whole — it is a few hundred bytes and it is what
 * makes the rest legible — and the cut is announced inline so a reader never
 * mistakes a truncated log for a short run.
 */
export function clampReport(
  full: string,
  header: string,
  max = LOG_SHARE_MAX_CHARS,
): { content: string; truncated: boolean } {
  if (full.length <= max) return { content: full, truncated: false };
  const marker = '\n[… oldest lines dropped to fit the upload limit …]\n';
  const budget = max - header.length - marker.length - 2;
  // A header alone over budget can't happen with real input, but if it did,
  // a hard slice beats emitting something the API will reject outright.
  if (budget <= 0) return { content: full.slice(0, max), truncated: true };
  const tail = full.slice(full.length - budget);
  // Start at a line boundary so the first surviving line isn't half a line.
  const nl = tail.indexOf('\n');
  return {
    content: `${header}${marker}${nl === -1 ? tail : tail.slice(nl + 1)}`,
    truncated: true,
  };
}
