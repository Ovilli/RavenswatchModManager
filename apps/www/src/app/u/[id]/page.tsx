'use client';
import { ApiError } from '@rsmm/api-client';
import { Badge, Input, Spinner, buttonVariants } from '@rsmm/ui';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Search } from 'lucide-react';
import Link from 'next/link';
import { use, useState } from 'react';
import { api } from '../../../lib/api';
import { ListingCard } from '../../components/listing-card';

type Sort = 'recent' | 'popular' | 'rating' | 'name';
const SORTS: { id: Sort; label: string }[] = [
  { id: 'recent', label: 'Recently updated' },
  { id: 'popular', label: 'Most downloaded' },
  { id: 'rating', label: 'Top rated' },
  { id: 'name', label: 'A–Z' },
];
// Past this many distinct tags the chip row stops being scannable, so only the
// most used ones get a chip; the search box still matches every tag.
const MAX_TAG_CHIPS = 12;

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0];
  if (!first) return '?';
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  const second = parts[1];
  return ((first[0] ?? '') + (second?.[0] ?? '')).toUpperCase();
}

export default function AuthorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('recent');
  const [category, setCategory] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);

  const detail = useQuery({
    queryKey: ['users', 'profile', id],
    queryFn: () => api.users.profile(id),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
  });

  if (detail.isLoading) {
    return (
      <main className="relative overflow-hidden animate-page-in">
        <div className="container mx-auto flex items-center justify-center px-6 py-24">
          <Spinner />
        </div>
      </main>
    );
  }

  if (detail.isError || !detail.data) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <main className="relative overflow-hidden animate-page-in">
        <div className="container mx-auto space-y-6 px-6 py-12">
          <Link href="/registry" className={buttonVariants({ variant: 'outline', size: 'sm' })}>
            <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Registry
          </Link>
          <p className="text-muted-foreground">
            {notFound ? `No author matches “${id}”.` : `Cannot reach API (${String(detail.error)})`}
          </p>
        </div>
      </main>
    );
  }

  const { user, mods, totalDownloads } = detail.data;
  const coAuthored = mods.filter((m) => m.role === 'coauthor').length;

  // Every author's mods arrive in one response, so filtering and sorting run
  // here rather than as another API round-trip.
  const categories = [...new Set(mods.map((m) => m.category).filter((c) => c != null))].sort();
  const tagCounts = new Map<string, number>();
  for (const m of mods) for (const t of m.tags) tagCounts.set(t, (tagCounts.get(t) ?? 0) + 1);
  const tagChips = [...tagCounts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, MAX_TAG_CHIPS)
    .map(([t]) => t);
  const needle = q.trim().toLowerCase();
  const shown = mods
    .filter((m) => !category || m.category === category)
    // AND semantics, like the registry: a mod must carry every picked tag.
    .filter((m) => tags.every((t) => m.tags.includes(t)))
    .filter(
      (m) =>
        !needle ||
        m.name.toLowerCase().includes(needle) ||
        (m.summary ?? '').toLowerCase().includes(needle) ||
        m.tags.some((t) => t.toLowerCase().includes(needle)),
    )
    .sort((a, b) => {
      if (sort === 'popular') return (b.downloads ?? 0) - (a.downloads ?? 0);
      if (sort === 'rating') return (b.rating ?? -1) - (a.rating ?? -1);
      if (sort === 'name') return a.name.localeCompare(b.name);
      return b.updatedAt.localeCompare(a.updatedAt);
    });
  const filtered = !!(needle || category || tags.length);
  const clear = () => {
    setQ('');
    setCategory(null);
    setTags([]);
  };
  const chip = (active: boolean) =>
    buttonVariants({ variant: active ? 'default' : 'outline', size: 'sm' });
  // GET /api/users/:id deliberately trims timestamps so a profile does not leak
  // account age, so `joinedAt` is normally absent — render the line only when a
  // server actually sends one.
  const joined = user.joinedAt
    ? new Date(user.joinedAt).toLocaleDateString(undefined, { year: 'numeric', month: 'long' })
    : null;

  return (
    <main className="relative overflow-hidden animate-page-in">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_right,hsl(var(--gilt)/0.06),transparent_50%)]" />
      <div className="relative container mx-auto space-y-8 px-6 py-12">
        <Link href="/registry" className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          <ArrowLeft className="mr-1.5 h-4 w-4" /> Back to Registry
        </Link>

        <header className="flex flex-col items-start gap-5 sm:flex-row sm:items-center">
          <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border bg-muted text-xl font-semibold text-foreground">
            {user.image ? (
              <img src={user.image} alt={user.name} className="h-full w-full object-cover" />
            ) : (
              <span>{initialsFor(user.name)}</span>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-3xl font-bold tracking-tight">{user.name}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {user.handle ? `@${user.handle}` : ''}
              {user.handle && joined ? ' · ' : ''}
              {joined ? `joined ${joined}` : ''}
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
              <Badge variant="outline">
                {mods.length} mod{mods.length === 1 ? '' : 's'}
                {coAuthored > 0 ? ` · ${coAuthored} co-authored` : ''}
              </Badge>
              {totalDownloads != null ? (
                <Badge variant="outline">{totalDownloads.toLocaleString()} total downloads</Badge>
              ) : null}
            </div>
          </div>
        </header>

        {mods.length === 0 ? (
          <p className="text-muted-foreground">This author has not published any mods yet.</p>
        ) : (
          <section className="space-y-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-xl font-bold tracking-tight">Published mods</h2>
              {filtered ? (
                <p className="text-sm text-muted-foreground">
                  {shown.length} of {mods.length} shown
                </p>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[220px] flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  type="search"
                  aria-label={`Search ${user.name}'s mods`}
                  placeholder="Search by name, summary or tag…"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  className="pl-9"
                />
              </div>
              {SORTS.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  aria-pressed={sort === o.id}
                  onClick={() => setSort(o.id)}
                  className={chip(sort === o.id)}
                >
                  {o.label}
                </button>
              ))}
            </div>

            {categories.length > 1 || tagChips.length > 0 ? (
              <div className="flex flex-wrap items-center gap-2">
                {categories.length > 1 ? (
                  <>
                    <span className="text-xs text-muted-foreground">Category</span>
                    <button
                      type="button"
                      aria-pressed={!category}
                      onClick={() => setCategory(null)}
                      className={chip(!category)}
                    >
                      All
                    </button>
                    {categories.map((c) => (
                      <button
                        key={c}
                        type="button"
                        aria-pressed={category === c}
                        onClick={() => setCategory(category === c ? null : c)}
                        className={`${chip(category === c)} capitalize`}
                      >
                        {c}
                      </button>
                    ))}
                  </>
                ) : null}
                {tagChips.length > 0 ? (
                  <>
                    <span className="ml-1 text-xs text-muted-foreground">Tags</span>
                    {tagChips.map((t) => {
                      const on = tags.includes(t);
                      return (
                        <button
                          key={t}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setTags(on ? tags.filter((x) => x !== t) : [...tags, t])}
                          className={chip(on)}
                        >
                          {t}
                        </button>
                      );
                    })}
                  </>
                ) : null}
                {filtered ? (
                  <button
                    type="button"
                    onClick={clear}
                    className={buttonVariants({ variant: 'ghost', size: 'sm' })}
                  >
                    Clear filters
                  </button>
                ) : null}
              </div>
            ) : null}

            {shown.length === 0 ? (
              <div className="grimoire-card flex flex-col items-center gap-3 p-10 text-center">
                <p className="text-sm text-muted-foreground">No mods match these filters.</p>
                <button
                  type="button"
                  onClick={clear}
                  className={buttonVariants({ variant: 'outline', size: 'sm' })}
                >
                  Clear filters
                </button>
              </div>
            ) : null}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {shown.map((m) => (
                <ListingCard key={m.id} kind="mod" item={m} headingLevel={3} />
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
