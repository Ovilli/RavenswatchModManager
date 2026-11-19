import { type Collection, type ModListItem, hasPrivateOnlyTag } from '@rsmm/schemas';
import { RegistryListingCard } from '@rsmm/ui';
import { Edit2, ExternalLink } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { REGISTRY_CATEGORIES } from '../../lib/registry-query';

type CardMod = Pick<
  ModListItem,
  'slug' | 'name' | 'imageUrl' | 'summary' | 'latestVersion' | 'downloads' | 'updatedAt'
> &
  Partial<Pick<ModListItem, 'author' | 'rating' | 'featured' | 'nsfw' | 'tags'>> & {
    category?: string | null;
    ratingCount?: number;
    role?: 'owner' | 'coauthor';
  };

type CardCollection = Pick<
  Collection,
  'slug' | 'name' | 'imageUrl' | 'summary' | 'ownerName' | 'modCount'
>;

type ListingCardProps = { headingLevel?: 2 | 3 } & (
  | { kind: 'mod'; item: CardMod; mode?: 'browse' | 'manage' }
  | { kind: 'collection'; item: CardCollection; mode?: never }
);

/** Shared listing cards using the current registry presentation. */
export function ListingCard(props: ListingCardProps) {
  const { slug, name } = props.item;
  const mod = props.kind === 'mod' ? props.item : null;
  const collection = props.kind === 'collection' ? props.item : null;
  const manage = props.mode === 'manage';
  const href = (
    collection ? `/c/${slug}` : manage ? `/my-mods/${slug}` : `/registry/${slug}`
  ) as Route;
  const privateOnly = hasPrivateOnlyTag(mod?.tags);
  const category =
    REGISTRY_CATEGORIES.find(({ id }) => id === mod?.category)?.label ?? mod?.category;
  const listing =
    props.kind === 'collection'
      ? { ...props.item, author: props.item.ownerName }
      : { ...props.item, category };

  return (
    <RegistryListingCard
      listing={listing}
      href={href}
      privateOnly={privateOnly}
      headingLevel={props.headingLevel}
      footer={
        mod && manage ? (
          <div className="space-y-3">
            <div className="space-y-1 text-xs text-muted-foreground">
              {!mod.latestVersion ? (
                <p className="text-amber-500">No version published yet</p>
              ) : null}
              <p>Updated {new Date(mod.updatedAt).toLocaleDateString()}</p>
            </div>
            <div className="flex gap-2">
              <Link
                href={href}
                className="inline-flex flex-1 items-center justify-center gap-1 rounded-md bg-secondary px-3 py-2 text-sm hover:bg-secondary/80"
              >
                <Edit2 className="h-3.5 w-3.5" aria-hidden />
                Manage
              </Link>
              <Link
                href={`/registry/${slug}` as Route}
                className="inline-flex items-center justify-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm hover:bg-accent"
                title="View public page"
                aria-label={`View ${name} public page`}
              >
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </Link>
            </div>
          </div>
        ) : undefined
      }
    />
  );
}
