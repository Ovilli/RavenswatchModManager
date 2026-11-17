import type { RegistryListingGallery, RegistryModCard, getRegistryMedia } from '@rsmm/ui';
import type { ComponentProps } from 'react';
import type { TFunction } from './i18n-react';

// Keep translation calls in the desktop source tree so catalog coverage sees
// every message, including text rendered inside the shared registry components.
export function registryCardLabels(
  t: TFunction,
  mod: ComponentProps<typeof RegistryModCard>['mod'],
): Required<NonNullable<ComponentProps<typeof RegistryModCard>['labels']>> {
  const author = mod.author || t('unknown');
  return {
    author: t('unknown'),
    authorLine: t('by {author}', { author }),
    card: mod.author ? t('{name} by {author}', { name: mod.name, author }) : mod.name,
    preview: t('{name} preview', { name: mod.name }),
    featured: t('Featured'),
    nsfw: t('nsfw'),
    privateOnly: t('Private games only'),
    coauthor: t('Co-author'),
    downloads: t('{n} dl', { n: (mod.downloads ?? 0).toLocaleString(t.tag) }),
    downloadUnit: (mod.downloads ?? 0) === 1 ? t('download') : t('downloads'),
    rating: t('{rating} out of 5 stars', { rating: (mod.rating ?? 0).toFixed(1) }),
  };
}

export function registryMediaLabels(
  t: TFunction,
): Required<NonNullable<Parameters<typeof getRegistryMedia>[1]>> {
  return {
    cover: (name) => t('{name} cover', { name }),
    screenshot: (name, n) => t('{name} screenshot {n}', { name, n }),
    video: (name, n) => t('{name} video {n}', { name, n }),
  };
}

export function registryGalleryLabels(
  t: TFunction,
  name: string,
): Required<NonNullable<ComponentProps<typeof RegistryListingGallery>['labels']>> {
  return {
    imageUnavailable: t('Image unavailable'),
    empty: t('No images added yet.'),
    watchVideo: t('Watch video'),
    opensInNewTab: t('Opens in a new tab'),
    gallery: t('{name} images and videos', { name }),
    matureContent: t('This mod contains mature content.'),
    showMedia: t('Show media'),
    view: (label) => t('View {label}', { label }),
    showAllMedia: (n) => t('Show all media ({n})', { n }),
    viewFullImage: t('View full image'),
    viewer: t('{name} media viewer', { name }),
    close: t('Close media viewer'),
    previous: t('Previous media'),
    next: t('Next media'),
    choose: t('Choose media'),
    show: (label) => t('Show {label}', { label }),
    video: t('Video'),
  };
}
