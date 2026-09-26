import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PAGE_UPDATED } from '../lib/page-dates';

const APP = join(__dirname);

/** Last commit date touching a segment's own page/layout, or null without git history. */
function gitDate(dir: string): string | null {
  const files = ['page.tsx', 'layout.tsx']
    .map((f) => join(APP, dir, f))
    .filter((f) => existsSync(f))
    // The root layout wraps every page; only the home page's own file counts.
    .filter((f) => dir !== '.' || f.endsWith('page.tsx'));
  try {
    const out = execFileSync('git', ['log', '-1', '--format=%cs', '--', ...files], {
      cwd: APP,
      encoding: 'utf8',
    }).trim();
    return out || null;
  } catch {
    return null;
  }
}

describe('PAGE_UPDATED', () => {
  for (const [path, { date, dir }] of Object.entries(PAGE_UPDATED)) {
    it(`${path || '/'} is current`, () => {
      expect(existsSync(join(APP, dir, 'page.tsx')), `${dir}/page.tsx`).toBe(true);
      const committed = gitDate(dir);
      // A shallow clone may not reach the commit; the full-history run catches it.
      if (!committed) return;
      expect(
        date >= committed,
        `${dir} was edited ${committed}; bump its PAGE_UPDATED date (${date})`,
      ).toBe(true);
    });
  }
});

describe('sitemap', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('gives every URL a stable lastmod', async () => {
    const api: Record<string, unknown> = {
      '/api/mods': [
        { slug: 'a', summary: 'x', updatedAt: '2030-01-02T00:00:00Z' },
        { slug: 'b', summary: '', updatedAt: '2031-01-01T00:00:00Z' },
      ],
      '/api/collections': [{ slug: 'c1', updatedAt: '2020-01-01T00:00:00Z' }],
      '/api/guides': [],
    };
    vi.stubGlobal('fetch', async (url: string) => {
      if (url.includes('api.github.com')) {
        return new Response(JSON.stringify({ published_at: '2030-05-05T00:00:00Z', assets: [] }));
      }
      const path = Object.keys(api).find((p) => url.includes(`${p}?`));
      return new Response(JSON.stringify(path ? api[path] : []));
    });
    const { default: sitemap } = await import('./sitemap');
    const first = await sitemap();
    const second = await sitemap();

    for (const e of first) expect(e.lastModified, e.url).toBeInstanceOf(Date);
    // Same data in, same dates out: no `now` anywhere.
    expect(second.map((e) => String(e.lastModified))).toEqual(
      first.map((e) => String(e.lastModified)),
    );

    const at = (u: string) =>
      (first.find((e) => e.url === `https://rsmm.me${u}`)?.lastModified as Date).toISOString();
    // Listing pages follow the newest entry they SHOW — the summary-less mod is not listed.
    expect(at('/registry')).toBe('2030-01-02T00:00:00.000Z');
    expect(at('/download')).toBe('2030-05-05T00:00:00.000Z');
    // Older data never drags a page below its own copy's date.
    expect(at('/c')).toBe(new Date(PAGE_UPDATED['/c']?.date ?? '').toISOString());
  });
});
