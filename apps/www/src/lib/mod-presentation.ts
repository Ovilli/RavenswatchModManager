import type { ModListItem, ModVersion } from '@rsmm/schemas';

export type ModMedia =
  | { kind: 'image'; url: string; label: string }
  | { kind: 'video'; url: string; label: string };

/** The cover is the first gallery image, not a separately cropped banner. */
export function getModMedia(
  mod: Pick<ModListItem, 'name' | 'imageUrl' | 'screenshots' | 'videos'>,
): ModMedia[] {
  const images = mod.imageUrl
    ? [
        {
          url: mod.imageUrl,
          caption:
            mod.screenshots?.find((shot) => shot.url === mod.imageUrl)?.caption ||
            `${mod.name} cover`,
        },
        ...(mod.screenshots ?? []),
      ]
    : (mod.screenshots ?? []);
  const seen = new Set<string>();
  const media: ModMedia[] = [];
  for (const image of images) {
    if (seen.has(image.url)) continue;
    seen.add(image.url);
    media.push({
      kind: 'image',
      url: image.url,
      label: image.caption || `${mod.name} screenshot ${media.length + 1}`,
    });
  }
  for (const [index, url] of (mod.videos ?? []).entries()) {
    if (seen.has(url)) continue;
    seen.add(url);
    media.push({ kind: 'video', url, label: `${mod.name} video ${index + 1}` });
  }
  return media;
}

export function getDownloadVersion(
  versions: ModVersion[],
  latestVersion?: string | null,
): ModVersion | undefined {
  return versions.find((version) => version.version === latestVersion) ?? versions[0];
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const unit = bytes < 1024 * 1024 ? 'KB' : 'MB';
  const value = bytes / (unit === 'KB' ? 1024 : 1024 * 1024);
  return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value)} ${unit}`;
}

export function formatModDate(date: string): string {
  return new Date(date).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
}
