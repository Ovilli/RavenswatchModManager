import { Hono } from 'hono';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Review replies, notification delete/paging and the review-email opt-out.
 * The real routers are mounted on a bare app with a fake signed-in user; the
 * DB is a recording stub, so these check the routes' own guards (who may
 * reply, what gets written, who gets mailed) without a database.
 */
process.env.DATABASE_URL ??= 'postgres://user:pass@localhost:5432/db';
process.env.BETTER_AUTH_SECRET ??= 'x'.repeat(32);

const MOD = {
  id: '00000000-0000-4000-8000-000000000001',
  slug: 'm',
  name: 'Mod',
  ownerId: 'owner',
  takedownStatus: 'active',
};
const REVIEW_ID = '00000000-0000-4000-8000-0000000000aa';
const NOTE_ID = '00000000-0000-4000-8000-0000000000bb';

const state = {
  review: null as null | { id: string; userId: string; ownerReply: string | null },
  emailUser: null as null | { email: string; emailReviews: boolean },
  updates: [] as unknown[],
  deletes: 0,
};

vi.mock('@rsmm/db', () => {
  const chain = (result: unknown) => {
    const p = Promise.resolve(result) as Promise<unknown> & Record<string, unknown>;
    for (const k of ['from', 'where', 'orderBy', 'limit', 'innerJoin', 'returning']) {
      p[k] = () => chain(result);
    }
    return p;
  };
  return {
    getDb: () => ({
      query: {
        mods: { findFirst: async () => MOD },
        modReviews: { findFirst: async () => state.review },
      },
      select: () => chain(state.emailUser ? [state.emailUser] : []),
      insert: () => ({ values: () => Promise.resolve() }),
      update: () => ({
        set: (v: unknown) => {
          state.updates.push(v);
          return chain([]);
        },
      }),
      delete: () => {
        state.deletes++;
        return chain([]);
      },
    }),
    schema: new Proxy({}, { get: () => new Proxy({}, { get: () => 'col' }) }),
  };
});
vi.mock('../src/rate-limit.js', () => ({
  createRateLimiter: () => async (_c: unknown, next: () => Promise<void>) => next(),
}));
vi.mock('../src/mod-access.js', () => ({
  canManageMod: async (_mod: unknown, userId: string) =>
    userId === 'owner' || userId === 'coauthor',
}));
const sendMail = vi.fn(async () => {});
vi.mock('../src/mailer.js', async (orig) => ({
  ...(await orig<typeof import('../src/mailer.js')>()),
  sendMail,
}));
vi.mock('../src/env.js', async (orig) => ({
  ...(await orig<typeof import('../src/env.js')>()),
  smtpConfigured: () => true,
}));

const { modsRouter } = await import('../src/routes/mods.js');
const { meRouter } = await import('../src/routes/me.js');

function appAs(userId: string | null) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user' as never, (userId ? { id: userId, name: userId } : null) as never);
    await next();
  });
  app.route('/api/mods', modsRouter);
  app.route('/api/me', meRouter);
  return app;
}

const reply = (userId: string | null, body = 'thanks!') =>
  appAs(userId).request(`/api/mods/m/reviews/${REVIEW_ID}/reply`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ body }),
  });

beforeEach(() => {
  state.review = { id: REVIEW_ID, userId: 'reviewer', ownerReply: null };
  state.emailUser = { email: 'reviewer@example.com', emailReviews: true };
  state.updates = [];
  state.deletes = 0;
  sendMail.mockClear();
});

describe('review replies', () => {
  it('requires sign-in and authorship', async () => {
    expect((await reply(null)).status).toBe(401);
    expect((await reply('stranger')).status).toBe(403);
    expect(state.updates).toHaveLength(0);
  });

  it('lets owner and co-authors reply, and emails the reviewer once', async () => {
    expect((await reply('owner')).status).toBe(200);
    expect(state.updates[0]).toMatchObject({ ownerReply: 'thanks!' });
    expect(sendMail).toHaveBeenCalledTimes(1);
    expect(sendMail.mock.calls[0]?.[0]).toMatchObject({ to: 'reviewer@example.com' });

    // Editing an existing reply notifies in-app only.
    state.review = { id: REVIEW_ID, userId: 'reviewer', ownerReply: 'thanks!' };
    expect((await reply('coauthor', 'edited')).status).toBe(200);
    expect(sendMail).toHaveBeenCalledTimes(1);
  });

  it('does not email a reviewer who turned review emails off', async () => {
    state.emailUser = { email: 'reviewer@example.com', emailReviews: false };
    expect((await reply('owner')).status).toBe(200);
    expect(sendMail).not.toHaveBeenCalled();
  });

  it('404s for a review that is not on this mod', async () => {
    state.review = null;
    expect((await reply('owner')).status).toBe(404);
  });

  it('rejects an empty reply', async () => {
    expect((await reply('owner', '   ')).status).toBe(400);
  });
});

describe('notifications', () => {
  it('delete requires sign-in', async () => {
    const res = await appAs(null).request('/api/me/notifications', {
      method: 'DELETE',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });
    expect(res.status).toBe(401);
    expect(state.deletes).toBe(0);
  });

  it('deletes one or all', async () => {
    for (const body of [JSON.stringify({ id: NOTE_ID }), '{}']) {
      const res = await appAs('owner').request('/api/me/notifications', {
        method: 'DELETE',
        headers: { 'content-type': 'application/json' },
        body,
      });
      expect(res.status).toBe(200);
    }
    expect(state.deletes).toBe(2);
  });

  it('rejects a malformed paging cursor', async () => {
    const res = await appAs('owner').request('/api/me/notifications?before=nope');
    expect(res.status).toBe(400);
  });
});
