import type { TelemetryRun } from '@rsmm/schemas';
import { isTauri } from '@tauri-apps/api/core';
import { useApp } from '../store';
import { api } from './api';
import { RSMM_VERSION } from './app-version';
import { appendLauncherLog } from './launcher-log';

export function detectOs(): TelemetryRun['os'] {
  if (typeof navigator === 'undefined') return 'unknown';
  const p = navigator.platform.toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (p.includes('win') || ua.includes('windows')) return 'windows';
  if (p.includes('linux') || ua.includes('linux')) return 'linux';
  return 'unknown';
}

/** Only a packaged build running inside the Tauri shell reports crashes. */
export function shouldUploadCrash(dev = import.meta.env.DEV, native = isTauri()): boolean {
  return !dev && native;
}

/**
 * CLI refusals that tell the player to fix their setup. Together they were
 * ~250 of the 270 crash rows from shipped builds. Matched on the CLI's
 * English text (it is never translated — see lib/errors.ts).
 */
const EXPECTED_USER_ERRORS = [
  'Could not autodetect Ravenswatch install',
  'Ravenswatch is running',
  'another rsmm process is working on this install',
];

export function isExpectedUserError(message: string): boolean {
  return EXPECTED_USER_ERRORS.some((s) => message.includes(s));
}

const reportedThisSession = new Set<string>();

/** True the first time an (errorClass, message) pair is seen this launch. */
export function firstInSession(errorClass: string, message: string): boolean {
  const key = `${errorClass}\u0000${message}`;
  if (reportedThisSession.has(key)) return false;
  reportedThisSession.add(key);
  return true;
}

export async function reportCrash(args: {
  errorClass: string;
  message: string;
  stacktrace: string;
  context?: Record<string, unknown>;
}) {
  const crashPayload = {
    errorClass: args.errorClass,
    message: args.message,
    context: args.context ?? null,
  };
  // The local log entry below is written either way — it never leaves the
  // machine and is what `rsmm doctor` / a bug report needs. Only the upload
  // is opt-out (Settings → Privacy).
  if (!useApp.getState().settings.crashReports) {
    await appendLauncherLog('error', 'Frontend crash (reporting disabled)', crashPayload);
    return;
  }
  // Dev servers (`pnpm dev`, or the Vite page opened in a plain browser) are
  // not shipped builds — they were ~77% of production crash rows, mostly
  // HMR-reload storms. Never upload from them.
  if (!shouldUploadCrash()) {
    await appendLauncherLog('error', 'Frontend crash (dev build, not uploaded)', crashPayload);
    return;
  }
  // The CLI's own guard refusals are the player's setup, not a bug.
  if (isExpectedUserError(args.message)) {
    await appendLauncherLog('error', 'Frontend error (expected, not uploaded)', crashPayload);
    return;
  }
  // A retry loop re-throws the same error; one row per launch is enough.
  if (!firstInSession(args.errorClass, args.message)) {
    await appendLauncherLog('error', 'Frontend crash (repeat, not uploaded)', crashPayload);
    return;
  }
  try {
    await api.telemetry.crash({
      rsmmVersion: RSMM_VERSION,
      os: detectOs(),
      errorClass: args.errorClass,
      message: args.message,
      stacktrace: args.stacktrace,
      context: args.context,
    });
  } catch {
    // best-effort
  }
  await appendLauncherLog('error', 'Frontend crash reported', crashPayload);
}

const INSTALL_ID_KEY = 'rsmm.installId';

/** Tell the API this install was opened today. The id is random and local —
 * the API upserts one row per install per day, so calling this on every
 * launch (or from every window) is fine. */
export async function pingInstall() {
  if (!useApp.getState().settings.usageReports) return;
  try {
    let installId = localStorage.getItem(INSTALL_ID_KEY);
    if (!installId) {
      installId = crypto.randomUUID();
      localStorage.setItem(INSTALL_ID_KEY, installId);
    }
    await api.telemetry.ping({ installId, rsmmVersion: RSMM_VERSION, os: detectOs() });
  } catch {
    // best-effort
  }
}

/**
 * tauri-plugin-shell injects an init script (unconditionally) that hooks every
 * `<a target="_blank">` click and fire-and-forgets `plugin:shell|open`. We do
 * not grant `shell:allow-open` — granting it would open each link twice — so
 * that invoke always rejects, unhandled. The link itself still opens through
 * the opener-plugin handler in main.tsx, so the rejection is pure noise.
 */
export function isShellOpenAclNoise(message: string): boolean {
  return message.includes('plugin:shell|open not allowed');
}

export function wireGlobalErrorHandlers() {
  if (typeof window === 'undefined') return;
  window.addEventListener('error', (e) => {
    void reportCrash({
      errorClass: e.error?.name ?? 'Error',
      message: e.error?.message ?? e.message,
      stacktrace: e.error?.stack ?? '',
    });
  });
  window.addEventListener('unhandledrejection', (e) => {
    const reason = e.reason instanceof Error ? e.reason : new Error(String(e.reason));
    if (isShellOpenAclNoise(reason.message)) return;
    void reportCrash({
      errorClass: reason.name,
      message: reason.message,
      stacktrace: reason.stack ?? '',
    });
  });
}

/** Structural slice of `LoaderPerfReport` (lib/rsmm.ts), kept here so this
 *  module does not import the CLI bridge just for a type. */
interface PerfFigures {
  calls: number;
  lua_ms: number;
  max_ms: number;
  max_in: string;
  slow: number;
}
interface PerfReport {
  session_s?: number;
  session?: string;
  lua_ms: number;
  slow_calls: number;
  wait_max_ms: number;
  session_wait_max_ms: number;
  mods: Record<
    string,
    PerfFigures & { heap_kb: number; heap_first_kb: number; session?: PerfFigures }
  >;
}

const PERF_TOP_MODS = 12;
const SLOW_MS = 16;

/**
 * The `/telemetry/run` body for one game session's loader performance report
 * (issue #175). Whole-session figures where the loader has them, the busiest
 * mods first, trimmed well inside the 50-key / 10 KB payload limit. `ok` is
 * false when anything held the game up for a frame or more.
 */
export function perfRunBody(report: PerfReport, os = detectOs()): TelemetryRun {
  const mods = Object.entries(report.mods)
    .map(([id, m]) => {
      const s = m.session ?? m;
      return {
        id,
        luaMs: Math.round(s.lua_ms),
        calls: s.calls,
        maxMs: Math.round(s.max_ms * 10) / 10,
        maxIn: s.max_in.slice(0, 48),
        slow: s.slow,
        heapKb: m.heap_kb,
        heapGrowKb: m.heap_kb - m.heap_first_kb,
      };
    })
    .sort((a, b) => b.luaMs - a.luaMs)
    .slice(0, PERF_TOP_MODS);
  const slow = mods.reduce((n, m) => n + m.slow, 0);
  const waitMax = Math.max(report.session_wait_max_ms, report.wait_max_ms);
  return {
    rsmmVersion: RSMM_VERSION,
    os,
    ok: slow === 0 && waitMax < SLOW_MS,
    durationMs: report.session_s ? Math.round(report.session_s * 1000) : undefined,
    payload: {
      kind: 'loader-perf',
      slowCalls: slow,
      waitMaxMs: Math.round(waitMax * 10) / 10,
      modCount: Object.keys(report.mods).length,
      mods,
    },
  };
}

const PERF_SENT_KEY = 'rsmm.perfSentSession';

/** Send the last finished game session's performance report, once. Skipped
 *  while the game runs (the report is still being rewritten) and when usage
 *  reports are off. Best-effort: any failure just tries again next start. */
export async function reportLoaderPerf() {
  if (!useApp.getState().settings.usageReports || !shouldUploadCrash()) return;
  try {
    const { gameStatus, loaderPerf } = await import('./rsmm');
    const st = await gameStatus();
    if (!st || st.running) return;
    const res = await loaderPerf();
    const report = res?.report;
    if (!report) return;
    const key = report.session ?? String(res.mtime);
    if (localStorage.getItem(PERF_SENT_KEY) === key) return;
    await api.telemetry.run(perfRunBody(report));
    localStorage.setItem(PERF_SENT_KEY, key);
  } catch {
    // best-effort
  }
}
