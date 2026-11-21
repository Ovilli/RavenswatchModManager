import { zValidator } from '@hono/zod-validator';
import { getDb, schema } from '@rsmm/db';
import { modModerationMessageSchema } from '@rsmm/schemas';
import { asc, eq } from 'drizzle-orm';
import { Hono } from 'hono';
import { z } from 'zod';
import { isAdmin } from '../admin.js';
import { canManageMod } from '../mod-access.js';
import { notify } from '../notify.js';
import { createRateLimiter } from '../rate-limit.js';
import type { AppEnv } from '../types.js';

/**
 * The private moderation thread on a mod: messages between the mod's team
 * (owner + co-authors) and the moderators, interleaved with every takedown
 * status change (written by the moderation takedown route). Nobody else can
 * read it, and it works on hidden/removed mods too — that is when it matters.
 */
export const modModerationRouter = new Hono<AppEnv>();

const slugParamSchema = z.object({
  slug: z
    .string()
    .min(1)
    .max(128)
    .regex(/^[a-z0-9_-]+$/),
});

const limiter = createRateLimiter({
  name: 'mod-moderation',
  windowMs: 60_000,
  maxHits: 20,
  keyFrom: (c) => c.get('user')?.id ?? c.req.header('x-real-ip') ?? 'anon',
});

type ModRow = {
  id: string;
  slug: string;
  name: string;
  ownerId: string | null;
  takedownStatus: string;
  takedownReason: string | null;
  updatedAt: Date;
};

/** The mod, if the signed-in viewer may use its moderation thread. */
async function threadAccess(
  slug: string,
  userId: string,
): Promise<{ mod: ModRow; moderator: boolean } | 'missing' | 'forbidden'> {
  const mod = await getDb().query.mods.findFirst({
    where: eq(schema.mods.slug, slug),
    columns: {
      id: true,
      slug: true,
      name: true,
      ownerId: true,
      takedownStatus: true,
      takedownReason: true,
      updatedAt: true,
    },
  });
  if (!mod) return 'missing';
  const moderator = isAdmin(userId);
  if (!moderator && !(await canManageMod(mod, userId))) return 'forbidden';
  return { mod, moderator };
}

modModerationRouter.get('/:slug/moderation', zValidator('param', slugParamSchema), async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const access = await threadAccess(c.req.valid('param').slug, user.id);
  // 404 rather than 403 to anyone outside the team: the thread's existence is
  // not public information.
  if (access === 'missing' || access === 'forbidden') return c.json({ error: 'not found' }, 404);

  const rows = await getDb()
    .select({
      id: schema.modModerationMessages.id,
      kind: schema.modModerationMessages.kind,
      body: schema.modModerationMessages.body,
      fromStatus: schema.modModerationMessages.fromStatus,
      toStatus: schema.modModerationMessages.toStatus,
      fromModerator: schema.modModerationMessages.fromModerator,
      createdAt: schema.modModerationMessages.createdAt,
      authorId: schema.modModerationMessages.authorId,
      authorName: schema.users.name,
      authorImage: schema.users.image,
    })
    .from(schema.modModerationMessages)
    .leftJoin(schema.users, eq(schema.modModerationMessages.authorId, schema.users.id))
    .where(eq(schema.modModerationMessages.modId, access.mod.id))
    .orderBy(asc(schema.modModerationMessages.createdAt))
    .limit(500);

  const items = rows.map((r) => ({ ...r, createdAt: r.createdAt.toISOString() }));
  // Takedowns made before this thread existed left no status row. Show the
  // mod's current takedown (and its reason) as the opening entry instead of an
  // empty thread under a "Hidden" status.
  const { mod } = access;
  if (mod.takedownStatus !== 'active' && !items.some((i) => i.kind === 'status')) {
    items.unshift({
      id: `takedown-${mod.id}`,
      kind: 'status',
      body: mod.takedownReason,
      fromStatus: null,
      toStatus: mod.takedownStatus,
      fromModerator: true,
      createdAt: mod.updatedAt.toISOString(),
      authorId: null,
      authorName: null,
      authorImage: null,
    });
  }

  return c.json({ viewerIsModerator: access.moderator, items });
});

modModerationRouter.post(
  '/:slug/moderation',
  limiter,
  zValidator('param', slugParamSchema),
  zValidator('json', modModerationMessageSchema),
  async (c) => {
    const user = c.get('user');
    if (!user) return c.json({ error: 'unauthorized' }, 401);
    const access = await threadAccess(c.req.valid('param').slug, user.id);
    if (access === 'missing' || access === 'forbidden') {
      return c.json({ error: 'not found' }, 404);
    }
    const { body } = c.req.valid('json');
    const db = getDb();
    const [row] = await db
      .insert(schema.modModerationMessages)
      .values({
        modId: access.mod.id,
        authorId: user.id,
        kind: 'message',
        body,
        fromModerator: access.moderator,
      })
      .returning();

    // A moderator's message reaches the whole team (in-app; the owner also by
    // email). A team message does NOT notify staff — the thread says so.
    if (access.moderator) {
      const coAuthors = await db
        .select({ userId: schema.modAuthors.userId })
        .from(schema.modAuthors)
        .where(eq(schema.modAuthors.modId, access.mod.id));
      const team = new Set(
        [access.mod.ownerId, ...coAuthors.map((a) => a.userId)].filter(
          (id): id is string => !!id && id !== user.id,
        ),
      );
      const owner = access.mod.ownerId
        ? await db.query.users.findFirst({
            where: eq(schema.users.id, access.mod.ownerId),
            columns: { email: true },
          })
        : undefined;
      await Promise.all(
        [...team].map((userId) =>
          notify({
            userId,
            type: 'mod_moderation_message',
            title: `A moderator messaged you about "${access.mod.name}"`,
            body,
            link: `/registry/${access.mod.slug}#moderation`,
            email: userId === access.mod.ownerId ? (owner?.email ?? null) : null,
          }),
        ),
      );
    }

    return c.json({ ok: true, id: row?.id ?? null });
  },
);
