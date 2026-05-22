import type { TelemetryRun } from '@rsmm/schemas';
import { api } from './api';
import { appendLauncherLog } from './launcher-log';

const RSMM_VERSION = import.meta.env.VITE_RSMM_VERSION ?? '0.0.0-dev';

export function detectOs(): TelemetryRun['os'] {
  if (typeof navigator === 'undefined') return 'unknown';
  const p = navigator.platform.toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (p.includes('win') || ua.includes('windows')) return 'windows';
  if (p.includes('mac') || ua.includes('mac os')) return 'macos';
  if (p.includes('linux') || ua.includes('linux')) return 'linux';
  return 'unknown';
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
    void reportCrash({
      errorClass: reason.name,
      message: reason.message,
      stacktrace: reason.stack ?? '',
    });
  });
}
