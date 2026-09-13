// Database side of API-token authentication. The pure rules (token format,
// hashing, which routes a token may reach) live in api-tokens.ts.

import { getDb, schema } from '@rsmm/db';
import { and, eq, gt, isNull } from 'drizzle-orm';
import { hashToken } from './api-tokens.js';
import type { Session } from './auth.js';
import { errString, log } from './logger.js';

/** Don't rewrite `last_used_at` more often than this per token. */
const LAST_USED_RESOLUTION_MS = 60_000;

/**
 * The owner of a live token, or null when the token is unknown, revoked or
 * expired. Ban and email-verification gates are applied by the caller (the
 * session middleware), exactly as for a cookie session.
 */
export async function resolveTokenUser(
  token: string,
): Promise<{ user: Session['user']; tokenId: string } | null> {
  const db = getDb();
  const now = new Date();
  const rows = await db
    .select({ token: schema.apiTokens, user: schema.users })
    .from(schema.apiTokens)
    .innerJoin(schema.users, eq(schema.apiTokens.userId, schema.users.id))
    .where(
      and(
        eq(schema.apiTokens.tokenHash, hashToken(token)),
        isNull(schema.apiTokens.revokedAt),
        gt(schema.apiTokens.expiresAt, now),
      ),
    )
    .limit(1)
    .catch((err: unknown) => {
      log.error('api token lookup failed', { err: errString(err) });
      return [];
    });
  const row = rows[0];
  if (!row) return null;

  const last = row.token.lastUsedAt?.getTime() ?? 0;
  if (now.getTime() - last > LAST_USED_RESOLUTION_MS) {
    db.update(schema.apiTokens)
      .set({ lastUsedAt: now })
      .where(eq(schema.apiTokens.id, row.token.id))
      .catch((err: unknown) =>
        log.warn('api token last-used update failed', { err: errString(err) }),
      );
  }
  return { user: row.user as unknown as Session['user'], tokenId: row.token.id };
}
