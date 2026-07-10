import { getDb, schema } from '@rsmm/db';
import { and, eq, isNull } from 'drizzle-orm';
import { smtpConfigured } from './env.js';
import { errString, log } from './logger.js';
import { sendMail } from './mailer.js';

export type NotificationType =
  | 'mod_flagged'
  | 'mod_takedown'
  | 'report_resolved'
  | 'mod_review'
  | 'mod_new_version';

interface NotifyInput {
  userId: string;
  type: NotificationType;
  title: string;
  body?: string | null;
  link?: string | null;
  /** When set (and SMTP is configured), also send an email to this address. */
  email?: string | null;
}

/**
 * Create one in-app notification and, when an email address + SMTP are present,
 * also send it as an email. Never throws — a notification/email failure must
 * not roll back the action that triggered it.
 */
export async function notify(input: NotifyInput): Promise<void> {
  try {
    await getDb()
      .insert(schema.notifications)
      .values({
        userId: input.userId,
        type: input.type,
        title: input.title,
        body: input.body ?? null,
        link: input.link ?? null,
      });
  } catch (err) {
    log.error('failed to create notification', { err: errString(err), type: input.type });
  }

  if (input.email && smtpConfigured()) {
    try {
      const text = input.body ? `${input.title}\n\n${input.body}` : input.title;
      await sendMail({ to: input.email, subject: input.title, text });
    } catch (err) {
      log.error('failed to send notification email', { err: errString(err), type: input.type });
    }
  }
}

/**
 * Fan a notification out to every follower of a mod (in-app only — no email, to
 * avoid blasting inboxes on every release). Excludes `exceptUserId` (usually the
 * publisher). Batched insert.
 */
export async function notifyFollowers(
  modId: string,
  input: { type: NotificationType; title: string; body?: string | null; link?: string | null },
  exceptUserId?: string | null,
): Promise<void> {
  try {
    const db = getDb();
    const followers = await db
      .select({ userId: schema.modFollows.userId })
      .from(schema.modFollows)
      .where(eq(schema.modFollows.modId, modId));
    const recipients = followers.map((f) => f.userId).filter((id) => id !== exceptUserId);
    if (recipients.length === 0) return;
    await db.insert(schema.notifications).values(
      recipients.map((userId) => ({
        userId,
        type: input.type,
        title: input.title,
        body: input.body ?? null,
        link: input.link ?? null,
      })),
    );
  } catch (err) {
    log.error('failed to fan out follower notifications', { err: errString(err), modId });
  }
}

/** Unread count for a user. */
export async function unreadCount(userId: string): Promise<number> {
  const rows = await getDb()
    .select({ id: schema.notifications.id })
    .from(schema.notifications)
    .where(and(eq(schema.notifications.userId, userId), isNull(schema.notifications.readAt)));
  return rows.length;
}
