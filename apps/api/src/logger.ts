/**
 * Tiny structured logger + request-id middleware. No external dependencies
 * (matches rate-limit.ts). JSON lines in production for log aggregators;
 * compact human lines in dev. Replaces ad-hoc console.* so every record
 * carries a level and — within a request — a correlation id.
 */
import { isProduction } from './env.js';
import type { AppEnv } from './types.js';

type Level = 'debug' | 'info' | 'warn' | 'error';
const ORDER: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };

const configured =
  (process.env.LOG_LEVEL as Level | undefined) ?? (isProduction ? 'info' : 'debug');
const threshold = ORDER[configured] ?? ORDER.info;

export interface Logger {
  debug(msg: string, fields?: Record<string, unknown>): void;
  info(msg: string, fields?: Record<string, unknown>): void;
  warn(msg: string, fields?: Record<string, unknown>): void;
  error(msg: string, fields?: Record<string, unknown>): void;
  /** Derive a logger that stamps `bindings` (e.g. requestId) on every line. */
  child(bindings: Record<string, unknown>): Logger;
}

function emit(
  level: Level,
  bindings: Record<string, unknown>,
  msg: string,
  fields?: Record<string, unknown>,
): void {
  if (ORDER[level] < threshold) return;
  const time = new Date().toISOString();
  const sink = level === 'error' ? console.error : level === 'warn' ? console.warn : console.log;
  if (isProduction) {
    sink(JSON.stringify({ level, time, msg, ...bindings, ...fields }));
  } else {
    const extra = { ...bindings, ...fields };
    const tail = Object.keys(extra).length ? ` ${JSON.stringify(extra)}` : '';
    sink(`${time} ${level.toUpperCase().padEnd(5)} ${msg}${tail}`);
  }
}

function make(bindings: Record<string, unknown>): Logger {
  return {
    debug: (msg, fields) => emit('debug', bindings, msg, fields),
    info: (msg, fields) => emit('info', bindings, msg, fields),
    warn: (msg, fields) => emit('warn', bindings, msg, fields),
    error: (msg, fields) => emit('error', bindings, msg, fields),
    child: (extra) => make({ ...bindings, ...extra }),
  };
}

/** Base logger for module-load / no-request-context use (env, mailer, boot). */
export const log = make({});

/**
 * Assigns each request a correlation id (honouring an inbound `x-request-id`
 * from the proxy), echoes it on the response, and stashes a child logger at
 * `c.get('log')` for handlers.
 */
export async function requestId(
  c: import('hono').Context<AppEnv>,
  next: () => Promise<void>,
): Promise<void> {
  const id = c.req.header('x-request-id') ?? crypto.randomUUID();
  c.set('requestId', id);
  c.set('log', log.child({ requestId: id }));
  c.header('x-request-id', id);
  await next();
}
