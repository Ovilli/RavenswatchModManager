import type { RegistryListingGallery, RegistryListingCard, getRegistryMedia } from '@rsmm/ui';
import type { ComponentProps } from 'react';
import type { TFunction } from './i18n-react';

// Keep translation calls in the desktop source tree so catalog coverage sees
// every message, including text rendered inside the shared registry components.
export function registryCardLabels(
  t: TFunction,
  listing: ComponentProps<typeof RegistryListingCard>['listing'],
): Required<NonNullable<ComponentProps<typeof RegistryListingCard>['labels']>> {
  const author = listing.author || t('unknown');
  return {
    author: t('unknown'),
    authorLine: t('by {author}', { author }),
    card: listing.author ? t('{name} by {author}', { name: listing.name, author }) : listing.name,
    preview: t('{name} preview', { name: listing.name }),
    featured: t('Featured'),
    nsfw: t('nsfw'),
    privateOnly: t('Private games only'),
    coauthor: t('Co-author'),
    downloads: t('{n} dl', { n: (listing.downloads ?? 0).toLocaleString(t.tag) }),
    downloadUnit: (listing.downloads ?? 0) === 1 ? t('download') : t('downloads'),
    rating: t('{rating} out of 5 stars', { rating: (listing.rating ?? 0).toFixed(1) }),
    modCount: t.n(listing.modCount ?? 0, '{n} mod', '{n} mods'),
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
