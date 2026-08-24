const REPO = 'Ovilli/RavenswatchModManager';

export const RELEASES_URL = `https://github.com/${REPO}/releases`;
export const LATEST_RELEASE_URL = `${RELEASES_URL}/latest`;

export interface ReleaseAsset {
  name: string;
  url: string;
  /** Size in bytes, straight from the GitHub API. */
  size: number;
}

export interface LatestRelease {
  /** Tag of the latest published release, e.g. `v5.1.0`. */
  tag: string | null;
  /** Direct download for each platform's preferred installer, when present. */
  windows: string | null;
  linux: string | null;
  /** Every downloadable asset, so a caller can offer more than the primary. */
  assets: ReleaseAsset[];
}

interface GhAsset {
  name: string;
  browser_download_url: string;
  size?: number;
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

/** First asset matching any of `exts`, in preference order. */
export function pickAsset(assets: ReleaseAsset[], exts: string[]): ReleaseAsset | null {
  for (const ext of exts) {
    // `.sig` sits next to every installer as `<installer><ext>.sig`; endsWith on
    // the bare extension already excludes it, but updater metadata does not
    // carry one of these extensions at all.
    const hit = assets.find((a) => a.name.endsWith(ext));
    if (hit) return hit;
  }
  return null;
}

/** Human-readable size for a download button. */
export function formatBytes(bytes: number): string {
  const mb = bytes / 1024 / 1024;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
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
  const empty: LatestRelease = { tag: null, windows: null, linux: null, assets: [] };
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return empty;
    const data = await res.json();
    const raw: GhAsset[] = Array.isArray(data?.assets) ? data.assets : [];
    // Signatures and updater metadata are not downloads anyone wants offered.
    const assets: ReleaseAsset[] = raw
      .filter((a) => a?.name && a.browser_download_url && !a.name.endsWith('.sig'))
      .filter((a) => a.name !== 'latest.json')
      .map((a) => ({ name: a.name, url: a.browser_download_url, size: a.size ?? 0 }));
    return {
      tag: typeof data?.tag_name === 'string' ? data.tag_name : null,
      windows: pickAsset(assets, PICKERS.windows)?.url ?? null,
      linux: pickAsset(assets, PICKERS.linux)?.url ?? null,
      assets,
    };
  } catch {
    return empty;
  }
}
