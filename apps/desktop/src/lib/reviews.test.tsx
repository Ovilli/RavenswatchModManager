import { createApiClient } from '@rsmm/api-client';
import { ListingRatingSummary, ListingReviews, createReviewSource } from '@rsmm/ui/reviews';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';

const emptyReviews = { items: [], total: 0, averageRating: null };
const review = {
  id: '11111111-1111-4111-8111-111111111111',
  modId: '22222222-2222-4222-8222-222222222222',
  userId: 'player',
  userName: 'Rowan',
  userImage: null,
  rating: 4,
  title: 'Good choice',
  body: 'Worth trying.',
  ownerReply: 'Thanks!',
  ownerReplyAt: '2026-11-19T12:00:00.000Z',
  createdAt: '2026-11-19T12:00:00.000Z',
  updatedAt: '2026-11-19T12:00:00.000Z',
};

afterEach(() => vi.unstubAllGlobals());

describe('desktop registry review transport', () => {
  it.each(['mod', 'collection'] as const)(
    'uses the existing authenticated %s endpoints for every operation',
    async (target) => {
      const requests = vi
        .fn<typeof fetch>()
        .mockImplementation(async (_url, init) =>
          Response.json(init?.method === 'GET' ? emptyReviews : { ok: true }),
        );
      vi.stubGlobal('fetch', requests);
      const source = createReviewSource(api, target, 'more-choices');
      await source.list();
      await source.upsert({ rating: 4, title: 'Good choice', body: 'Worth trying.' });
      await source.reply(review.id, 'Thank you');
      await source.removeReply(review.id);
      await source.remove();
      const path = `/api/${target === 'mod' ? 'mods' : 'collections'}/more-choices/reviews`;
      expect(
        requests.mock.calls.map(([url, init]) => [
          new URL(String(url)).pathname,
          init?.method,
          init?.credentials,
        ]),
      ).toEqual([
        [path, 'GET', 'include'],
        [path, 'PUT', 'include'],
        [`${path}/${review.id}/reply`, 'PUT', 'include'],
        [`${path}/${review.id}/reply`, 'DELETE', 'include'],
        [path, 'DELETE', 'include'],
      ]);
      expect(JSON.parse(String(requests.mock.calls[1]?.[1]?.body))).toEqual({
        rating: 4,
        title: 'Good choice',
        body: 'Worth trying.',
      });
    },
  );

  it('bypasses CDN list caches after a review write', async () => {
    const requests = vi
      .fn<typeof fetch>()
      .mockImplementation(async (_url, init) =>
        Response.json(
          init?.method === 'GET' ? { items: [], total: 0, page: 1, pageSize: 24 } : { ok: true },
        ),
      );
    vi.stubGlobal('fetch', requests);
    await api.mods.upsertReview('more-choices', { rating: 5 });
    await api.mods.list({});
    expect(new URL(String(requests.mock.calls[1]?.[0])).searchParams.has('fresh')).toBe(true);
  });
});

function renderReviews({
  userId,
  isAuthor = false,
  ready = true,
  authPending = false,
}: {
  userId?: string;
  isAuthor?: boolean;
  ready?: boolean;
  authPending?: boolean;
}) {
  const source = createReviewSource(
    createApiClient({ baseUrl: 'https://example.test' }),
    'mod',
    'more-choices',
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (ready) client.setQueryData(source.queryKey, { items: [review], total: 1, averageRating: 4 });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ListingRatingSummary source={source} />
      <ListingReviews
        source={source}
        target="mod"
        userId={userId}
        isAuthor={isAuthor}
        authPending={authPending}
        signInLink={<a href="/signin">Sign in</a>}
        profileLink={(id, name, className) => (
          <a href={`/u/${id}`} className={className}>
            {name}
          </a>
        )}
      />
    </QueryClientProvider>,
  );
}

describe('shared web and desktop review states', () => {
  it('shows existing registry reviews, replies and rating to signed-out readers', () => {
    const html = renderReviews({});
    expect(html).toContain('Worth trying.');
    expect(html).toContain('Thanks!');
    expect(html).toContain('Rated 4 out of 5 from 1 review. Read reviews');
    expect(html).toContain('href="/signin"');
    expect(html).not.toContain('Post review');
  });
  it('lets a signed-in reviewer update and delete their existing review', () => {
    const html = renderReviews({ userId: 'player' });
    expect(html).toContain('Your review');
    expect(html).toContain('Update review');
    expect(html).toContain('Delete');
    expect(html).not.toContain('Edit reply');
  });
  it('gives authors reply controls without a self-review form', () => {
    const html = renderReviews({ userId: 'author', isAuthor: true });
    expect(html).toContain('Edit reply');
    expect(html).toContain('Delete reply');
    expect(html).not.toContain('Post review');
    expect(html).not.toContain('Review title (optional)');
  });
  it('waits for both session and saved review data before allowing a write', () => {
    expect(renderReviews({ userId: 'player', ready: false })).not.toContain('Post review');
    expect(renderReviews({ userId: 'player', authPending: true })).not.toContain('Update review');
  });
});
