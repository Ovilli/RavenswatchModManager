import { z } from 'zod';
import { osSchema } from './telemetry';

/**
 * Shared diagnostic logs ("share a link, not a wall of text").
 *
 * A support conversation about a crash used to mean pasting thousands of
 * loader lines into Discord, where the paste is truncated, unsearchable, and
 * strips the session banners that say which run it came from. A share instead
 * uploads the text once and hands back a URL.
 *
 * The payload is deliberately plain text, never markup: the viewer renders it
 * as text nodes, and the API answers JSON only, so nothing here is ever
 * interpreted. Size limits are the other half of that — this endpoint accepts
 * anonymous writes so an un-signed-in crash still gets a link, which makes it
 * the cheapest thing on the API to abuse as free text hosting.
 */

/** Which log the text came from. Drives the viewer's header and highlighting. */
export const logShareSourceSchema = z.enum(['loader', 'launcher', 'bundle']);
export type LogShareSource = z.infer<typeof logShareSourceSchema>;

/** Hard cap on stored text. ~150k chars is roughly 1500 loader lines — far
 *  more than any single run writes — and stays well under the API's 1 MB body
 *  limit even when every character JSON-escapes to six bytes. */
export const LOG_SHARE_MAX_CHARS = 150_000;

/** How long a share lives before the retention cron deletes it. */
export const LOG_SHARE_TTL_DAYS = 30;

export const logShareCreateSchema = z.object({
  content: z.string().min(1).max(LOG_SHARE_MAX_CHARS),
  source: logShareSourceSchema,
  rsmmVersion: z.string().max(32),
  os: osSchema,
  /** Free-form diagnostic header (game build, loader version, mod list…).
   *  Shown above the log in the viewer. Bounded like telemetry payloads. */
  meta: z
    .record(z.string(), z.unknown())
    .optional()
    .refine((v) => v === undefined || Object.keys(v).length <= 40, 'meta must have at most 40 keys')
    .refine((v) => {
      if (v === undefined) return true;
      try {
        return new TextEncoder().encode(JSON.stringify(v)).length <= 20_000;
      } catch {
        return false;
      }
    }, 'meta must not exceed 20KB serialized'),
});

export type LogShareCreate = z.infer<typeof logShareCreateSchema>;

/** What POST /api/logs answers: the id plus the URL to hand a human. */
export const logShareCreatedSchema = z.object({
  id: z.string(),
  url: z.string(),
  expiresAt: z.string(),
});

export type LogShareCreated = z.infer<typeof logShareCreatedSchema>;

/** What GET /api/logs/:id answers. */
export const logShareSchema = z.object({
  id: z.string(),
  source: logShareSourceSchema,
  rsmmVersion: z.string(),
  os: z.string(),
  content: z.string(),
  meta: z.record(z.string(), z.unknown()).nullable(),
  lineCount: z.number().int(),
  bytes: z.number().int(),
  createdAt: z.string(),
  expiresAt: z.string(),
});

export type LogShare = z.infer<typeof logShareSchema>;
