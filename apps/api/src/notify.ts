import { createHmac, timingSafeEqual } from 'node:crypto';
import { getDb, schema } from '@rsmm/db';
import { and, eq, isNull } from 'drizzle-orm';
import { env, smtpConfigured } from './env.js';
import { errString, log } from './logger.js';
import { sendMail } from './mailer.js';

export type NotificationType =
  | 'mod_flagged'
  | 'mod_takedown'
  | 'report_resolved'
  | 'mod_review'
  | 'collection_review'
  | 'guide_review'
  | 'review_reply'
  | 'mod_new_version';

interface NotifyInput {
  userId: string;
  type: NotificationType;
  title: string;
  body?: string | null;
  link?: string | null;
  /** When set (and SMTP is configured), also send an email to this address. */
  email?: string | null;
  /** Appended to the email only, never to the in-app notification. */
  emailFooter?: string | null;
  headers?: Record<string, string>;
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
      const text = [input.title, input.body, input.emailFooter].filter(Boolean).join('\n\n');
      await sendMail({ to: input.email, subject: input.title, text, headers: input.headers });
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

/**
 * Token for the one-click review-email unsubscribe link. Keyed on the auth
 * secret so the link needs no session and cannot be forged for another user.
 */
export function unsubscribeToken(userId: string): string {
  return createHmac('sha256', env.betterAuthSecret).update(`unsub:${userId}`).digest('base64url');
}

export function verifyUnsubscribeToken(userId: string, token: string): boolean {
  const want = Buffer.from(unsubscribeToken(userId));
  const got = Buffer.from(token);
  return want.length === got.length && timingSafeEqual(want, got);
}

/**
 * In-app notification about review activity, plus an email when `sendEmail`
 * and the recipient keeps `emailReviews` on. Every such email carries the
 * one-click unsubscribe link and List-Unsubscribe headers.
 */
async function notifyReviewActivity(input: {
  userId: string;
  type: NotificationType;
  title: string;
  body: string;
  link: string;
  sendEmail: boolean;
}): Promise<void> {
  let email: string | null = null;
  if (input.sendEmail) {
    try {
      const [user] = await getDb()
        .select({ email: schema.users.email, emailReviews: schema.users.emailReviews })
        .from(schema.users)
        .where(eq(schema.users.id, input.userId))
        .limit(1);
      if (user?.emailReviews) email = user.email;
    } catch (err) {
      log.error('failed to look up review email recipient', { err: errString(err) });
    }
  }
  const unsubscribe = `${env.betterAuthUrl}/api/unsubscribe?u=${encodeURIComponent(input.userId)}&t=${unsubscribeToken(input.userId)}`;
  await notify({
    userId: input.userId,
    type: input.type,
    title: input.title,
    body: input.body,
    link: input.link,
    email,
    emailFooter: `${env.webUrl}${input.link}\n\n—\nStop review emails: ${unsubscribe}\n(or turn off "Review emails" in your account settings)`,
    headers: {
      'List-Unsubscribe': `<${unsubscribe}>`,
      'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
    },
  });
}

/**
 * Tell the owner of a mod / collection / guide that it was reviewed. Only the
 * FIRST review from a user emails; an edit is in-app only.
 */
export async function notifyReview(input: {
  ownerId: string;
  type: 'mod_review' | 'collection_review' | 'guide_review';
  itemName: string;
  link: string;
  reviewerName: string | null;
  rating: number;
  title?: string | null;
  body?: string | null;
  isNew: boolean;
}): Promise<void> {
  await notifyReviewActivity({
    userId: input.ownerId,
    type: input.type,
    title: `${input.isNew ? 'New review' : 'Updated review'} on ${input.itemName}`,
    body: [
      `${input.reviewerName ?? 'Someone'} rated it ${input.rating}/5.`,
      input.title,
      input.body,
    ]
      .filter(Boolean)
      .join('\n\n'),
    link: input.link,
    sendEmail: input.isNew,
  });
}

/** Tell a reviewer the author replied. Only the first reply emails. */
export async function notifyReviewReply(input: {
  reviewerId: string;
  itemName: string;
  link: string;
  replierName: string | null;
  reply: string;
  isNew: boolean;
}): Promise<void> {
  await notifyReviewActivity({
    userId: input.reviewerId,
    type: 'review_reply',
    title: `${input.replierName ?? 'The author'} replied to your review of ${input.itemName}`,
    body: input.reply,
    link: input.link,
    sendEmail: input.isNew,
  });
}

/** Unread count for a user. */
export async function unreadCount(userId: string): Promise<number> {
  const rows = await getDb()
    .select({ id: schema.notifications.id })
    .from(schema.notifications)
    .where(and(eq(schema.notifications.userId, userId), isNull(schema.notifications.readAt)));
  return rows.length;
}
