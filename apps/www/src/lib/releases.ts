const REPO = 'Ovilli/RavenswatchModManager';

export const RELEASES_URL = `https://github.com/${REPO}/releases`;
export const LATEST_RELEASE_URL = `${RELEASES_URL}/latest`;

export interface LatestRelease {
  /** Tag of the latest published release, e.g. `v5.1.0`. */
  tag: string | null;
  /** Direct `browser_download_url` for each platform's installer, when present. */
  windows: string | null;
  linux: string | null;
}

interface GhAsset {
  name: string;
  browser_download_url: string;
}

/**
 * Assets are matched by extension rather than by a fixed filename because every
 * name carries the version (`Ravenswatch.Mod.Manager_5.1.0_x64-setup.exe`), so
 * GitHub's `releases/latest/download/<name>` shortcut cannot address them.
 *
 * Order is preference order. Windows has shipped both an NSIS `.exe` and an MSI
 * across releases, and Linux ships the AppImage and the `.deb` side by side —
 * take the first that exists so a release that drops one still resolves.
 */
const PICKERS: Record<'windows' | 'linux', string[]> = {
  windows: ['.msi', '.exe'],
  linux: ['.AppImage', '.deb'],
};

function pick(assets: GhAsset[], exts: string[]): string | null {
  for (const ext of exts) {
    // `.sig` sits next to every installer as `<installer><ext>.sig`; endsWith on
    // the bare extension already excludes it, but updater metadata does not
    // carry one of these extensions at all.
    const hit = assets.find((a) => a.name.endsWith(ext));
    if (hit) return hit.browser_download_url;
  }
  return null;
}

/**
 * Resolve the latest release's installer URLs, server-side.
 *
 * Deliberately not done in the browser: the site's CSP `connect-src` does not
 * include api.github.com (and should not — see next.config.mjs), so a client
 * fetch here would be blocked and the button would silently lose its href.
 *
 * Every field degrades to null on any failure; callers fall back to the release
 * page, which always exists.
 */
export async function getLatestRelease(): Promise<LatestRelease> {
  const empty: LatestRelease = { tag: null, windows: null, linux: null };
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return empty;
    const data = await res.json();
    const assets: GhAsset[] = Array.isArray(data?.assets) ? data.assets : [];
    return {
      tag: typeof data?.tag_name === 'string' ? data.tag_name : null,
      windows: pick(assets, PICKERS.windows),
      linux: pick(assets, PICKERS.linux),
    };
  } catch {
    return empty;
  }
}
