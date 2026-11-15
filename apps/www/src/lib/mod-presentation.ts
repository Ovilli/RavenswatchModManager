import type { ModListItem, ModVersion } from '@rsmm/schemas';
import { getRegistryMedia } from '@rsmm/ui/registry-media';
import type { RegistryMedia } from '@rsmm/ui';

export type ModMedia = RegistryMedia;

/** The cover is the first gallery image, not a separately cropped banner. */
export function getModMedia(
  mod: Pick<ModListItem, 'name' | 'imageUrl' | 'screenshots' | 'videos'>,
): ModMedia[] {
  return getRegistryMedia(mod);
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
