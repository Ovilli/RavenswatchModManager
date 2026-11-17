import type { RegistryMedia } from '../components/registry-listing-gallery';

interface RegistryMediaSource {
  name: string;
  imageUrl?: string | null;
  screenshots?: Array<{ url: string; caption?: string }>;
  videos?: string[];
}

/** Build the canonical cover, screenshot and video sequence for a listing. */
export function getRegistryMedia(
  mod: RegistryMediaSource,
  labels: {
    cover?: (name: string) => string;
    screenshot?: (name: string, index: number) => string;
    video?: (name: string, index: number) => string;
  } = {},
): RegistryMedia[] {
  const images = mod.imageUrl
    ? [
        {
          url: mod.imageUrl,
          caption:
            mod.screenshots?.find((shot) => shot.url === mod.imageUrl)?.caption ||
            (labels.cover?.(mod.name) ?? `${mod.name} cover`),
        },
        ...(mod.screenshots ?? []),
      ]
    : (mod.screenshots ?? []);
  const seen = new Set<string>();
  const media: RegistryMedia[] = [];
  for (const image of images) {
    if (seen.has(image.url)) continue;
    seen.add(image.url);
    media.push({
      kind: 'image',
      url: image.url,
      label:
        image.caption ||
        labels.screenshot?.(mod.name, media.length + 1) ||
        `${mod.name} screenshot ${media.length + 1}`,
    });
  }
  for (const [index, url] of (mod.videos ?? []).entries()) {
    if (seen.has(url)) continue;
    seen.add(url);
    media.push({
      kind: 'video',
      url,
      label: labels.video?.(mod.name, index + 1) ?? `${mod.name} video ${index + 1}`,
    });
  }
  return media;
}
