import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { describe, expect, it } from 'vitest';

const APP = join(__dirname);

function pages(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return pages(p);
    return name === 'page.tsx' ? [p] : [];
  });
}

/**
 * Every page must declare its own canonical, in the page or in a layout inside
 * its own route segment. Next inherits `alternates` from the root layout, so a
 * page that declares none silently ships `canonical: "/"` — which told Google
 * that /registry, /download, /guides, /c, /privacy and /legal were all the home
 * page, and it dropped them from the index.
 */
describe('canonical coverage', () => {
  for (const page of pages(APP)) {
    const rel = page.slice(APP.length + 1);
    // The home page is the one URL the root layout's `canonical: '/'` is for.
    if (rel === 'page.tsx') continue;
    it(rel, () => {
      let dir = dirname(page);
      let found = false;
      // Walk up to (not including) src/app: a segment layout counts, the root
      // layout does not.
      while (dir !== APP && !found) {
        for (const f of ['page.tsx', 'layout.tsx']) {
          try {
            const src = readFileSync(join(dir, f), 'utf8');
            // `noindex` pages opt out — they are not competing for a URL.
            if (src.includes('alternates') || src.includes('noindex')) found = true;
          } catch {
            /* no such file in this segment */
          }
        }
        dir = dirname(dir);
      }
      expect(found).toBe(true);
    });
  }
});
