import { env } from './env.js';

/**
 * Whether a user id is a platform admin. Admins are configured out-of-band via
 * the ADMIN_USER_IDS env var (comma, semicolon, space or newline separated) —
 * see admin-ids.ts. Shared by the
 * guides moderation queue and the mod moderation / reports console so there is
 * a single definition of "admin".
 */
export function isAdmin(userId?: string | null): boolean {
  return !!userId && env.adminUserIds.includes(userId);
}
