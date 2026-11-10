import type { ModDetailResponse } from '@rsmm/api-client';
import type { ModCategory, ModPatch } from '@rsmm/schemas';
import { type Screenshot, getListingPhotos, listingPhotoPatch } from './screenshot-gallery';

export interface ListingDraft {
  name: string;
  summary: string;
  description: string;
  category: ModCategory | null;
  tags: string;
  license: string;
  repoUrl: string;
  homepageUrl: string;
  nsfw: boolean;
  videos: string[];
  photos: Screenshot[];
}

export function readListingDraft({ mod, versions }: ModDetailResponse): ListingDraft {
  return {
    name: mod.name,
    summary: mod.summary ?? '',
    // Only older responses omit description. An explicitly cleared description
    // must not resurrect the copy from a previously published version.
    description:
      mod.description === undefined
        ? (versions[0]?.manifestJson.description ?? '')
        : (mod.description ?? ''),
    category: mod.category,
    tags: mod.tags.join(', '),
    license: mod.license ?? '',
    repoUrl: mod.repoUrl ?? '',
    homepageUrl: mod.homepageUrl ?? '',
    nsfw: mod.nsfw ?? false,
    videos: mod.videos ?? [],
    photos: getListingPhotos(mod.imageUrl, mod.screenshots),
  };
}

function listingPatch(draft: ListingDraft): ModPatch {
  return {
    name: draft.name.trim(),
    summary: draft.summary.trim() || null,
    description: draft.description.trim() || null,
    category: draft.category,
    tags: draft.tags
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean),
    license: draft.license.trim() || null,
    repoUrl: draft.repoUrl.trim() || null,
    homepageUrl: draft.homepageUrl.trim() || null,
    nsfw: draft.nsfw,
    videos: draft.videos,
    ...listingPhotoPatch(
      draft.photos.map((photo) => ({
        url: photo.url,
        caption: photo.caption?.trim() || undefined,
      })),
    ),
  };
}

/** Send one atomic patch, only for fields edited in this session. */
export function listingChanges(saved: ListingDraft, draft: ListingDraft): ModPatch {
  const before = listingPatch(saved);
  const after = listingPatch(draft);
  const changes: ModPatch = Object.fromEntries(
    Object.entries(after).filter(
      ([key, value]) => JSON.stringify(value) !== JSON.stringify(before[key as keyof ModPatch]),
    ),
  );
  if ('screenshots' in changes || 'imageUrl' in changes) {
    changes.screenshots = after.screenshots;
    changes.imageUrl = after.imageUrl;
  }
  return changes;
}
