'use client';

import { ApiError } from '@rsmm/api-client';
import type { CollectionDetail } from '@rsmm/schemas';
import { Button, Input, Spinner } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Layers, Lock, Pencil, Plus, Trash2 } from 'lucide-react';
import type { Route } from 'next';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';
import { formatModDate, getModMedia } from '../../../lib/mod-presentation';
import { useHydrated } from '../../../lib/use-hydrated';
import { ListingCard } from '../../components/listing-card';
import { ListingDetailView } from '../../components/listing-detail/listing-detail-view';
import {
  ListingRatingSummary,
  ListingReviews,
} from '../../components/listing-detail/listing-reviews';
import { CollectionEditor, describeCollectionError } from './collection-editor';
import './collection-detail.css';

export function CollectionDetailView({
  slug,
  initialData,
}: {
  slug: string;
  initialData?: CollectionDetail;
}) {
  const { data: session } = useSession();
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [addSlug, setAddSlug] = useState('');
  const detail = useQuery({
    queryKey: ['collections', slug],
    queryFn: () => api.collections.get(slug),
    initialData,
    initialDataUpdatedAt: 0,
    retry: (count, error) =>
      error instanceof ApiError && error.status === 404 ? false : count < 1,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['collections', slug] });
  const addMod = useMutation({
    mutationFn: (modSlug: string) => api.collections.addMod(slug, modSlug),
    onSuccess: async () => {
      setAddSlug('');
      await refresh();
    },
  });
  const removeMod = useMutation({
    mutationFn: (modSlug: string) => api.collections.removeMod(slug, modSlug),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api.collections.remove(slug),
    onSuccess: () => {
      window.location.href = '/c';
    },
  });
  const collection = hydrated ? (detail.data ?? initialData) : initialData;
  if (!collection) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <main className="mod-detail container">
        <Link href="/c" className="mod-back">
          <ArrowLeft size={16} aria-hidden />
          All collections
        </Link>
        <div className="mod-load-state">
          {detail.isError ? (
            <>
              <h1>{notFound ? 'Collection not found' : 'The collection couldn’t be loaded'}</h1>
              <p>
                {notFound ? `No collection matches “${slug}”.` : 'Please try again in a moment.'}
              </p>
              {!notFound ? (
                <button type="button" className="mod-reveal" onClick={() => detail.refetch()}>
                  Try again
                </button>
              ) : null}
            </>
          ) : (
            <>
              <Spinner />
              <output>Loading collection…</output>
            </>
          )}
        </div>
      </main>
    );
  }
  const isOwner = hydrated && session?.user?.id === collection.ownerId;
  const canEdit = hydrated && !!session && (isOwner || collection.canEdit === true);
  const author = collection.ownerName || 'Unknown curator';
  const modCount = collection.mods.length;

  return (
    <ListingDetailView
      className="collection-detail"
      name={collection.name}
      summary={collection.summary}
      media={getModMedia(collection)}
      breadcrumb={
        <Link href="/c" className="mod-back">
          <ArrowLeft size={16} aria-hidden />
          All collections
        </Link>
      }
      labels={
        !collection.isPublic ? (
          <div className="mod-labels">
            <span className="collection-visibility">
              <Lock size={13} aria-hidden />
              Private
            </span>
          </div>
        ) : null
      }
      stats={
        <>
          <a href="#included-mods">
            <Layers size={16} aria-hidden />
            {modCount} {modCount === 1 ? 'mod' : 'mods'}
          </a>
          <ListingRatingSummary target="collection" slug={slug} />
        </>
      }
      navigation={
        <>
          <a href="#included-mods">
            Included mods<span>{modCount}</span>
          </a>
          <a href="#reviews">Reviews</a>
        </>
      }
      sidebarLabel="Collection details"
      sidebar={
        <>
          <div className="mod-download-card collection-details-card">
            <div className="mod-author-row">
              <span className="mod-author-avatar" aria-hidden>
                {author.slice(0, 2).toUpperCase()}
              </span>
              <div className="mod-author">
                <span>Curated by</span>
                <Link href={`/u/${collection.ownerId}` as Route}>{author}</Link>
              </div>
            </div>
            <div className="mod-facts">
              <dl>
                <div>
                  <dt>Updated</dt>
                  <dd>
                    <time dateTime={collection.updatedAt}>
                      {formatModDate(collection.updatedAt)}
                    </time>
                  </dd>
                </div>
                <div>
                  <dt>Visibility</dt>
                  <dd>{collection.isPublic ? 'Public' : 'Private'}</dd>
                </div>
              </dl>
            </div>
          </div>
          {canEdit ? (
            <div className="collection-owner-actions">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setEditing(true)}
                disabled={editing || remove.isPending}
              >
                <Pencil size={14} aria-hidden />
                Edit collection
              </Button>
              {isOwner ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={remove.isPending || editing}
                  onClick={() => {
                    if (confirm('Delete this collection?')) remove.mutate();
                  }}
                >
                  <Trash2 size={14} aria-hidden />
                  {remove.isPending ? 'Deleting…' : 'Delete'}
                </Button>
              ) : null}
              {remove.isError ? <p role="alert">{describeCollectionError(remove.error)}</p> : null}
            </div>
          ) : null}
        </>
      }
    >
      {editing && canEdit ? (
        <CollectionEditor collection={collection} onClose={() => setEditing(false)} />
      ) : null}
      <section id="included-mods" className="mod-section" aria-label="Included mods">
        {canEdit ? (
          <form
            className="collection-add-mod"
            onSubmit={(event) => {
              event.preventDefault();
              if (addSlug.trim() && !addMod.isPending) addMod.mutate(addSlug.trim());
            }}
          >
            <label htmlFor="collection-mod-slug">Add a mod by slug</label>
            <div>
              <Input
                id="collection-mod-slug"
                value={addSlug}
                onChange={(event) => {
                  setAddSlug(event.target.value.toLowerCase());
                  addMod.reset();
                }}
                placeholder="mod-slug"
              />
              <Button type="submit" disabled={!addSlug.trim() || addMod.isPending}>
                <Plus size={16} aria-hidden />
                {addMod.isPending ? 'Adding…' : 'Add'}
              </Button>
            </div>
            {addMod.isError ? <p role="alert">{describeCollectionError(addMod.error)}</p> : null}
          </form>
        ) : null}
        {removeMod.isError ? (
          <p role="alert" className="mb-4 text-sm text-destructive">
            {describeCollectionError(removeMod.error)}
          </p>
        ) : null}
        {modCount === 0 ? (
          <p className="mod-description">
            {canEdit
              ? 'Add your first mod using its registry slug above.'
              : 'The curator hasn’t added any mods yet.'}
          </p>
        ) : (
          <ul className="collection-mod-grid">
            {collection.mods.map((mod) => (
              <li key={mod.id}>
                <ListingCard
                  kind="mod"
                  item={mod.nsfw ? { ...mod, imageUrl: null } : mod}
                  headingLevel={3}
                />
                {canEdit ? (
                  <button
                    type="button"
                    className="collection-remove-mod"
                    aria-label={`Remove ${mod.name} from collection`}
                    disabled={removeMod.isPending}
                    onClick={() => removeMod.mutate(mod.slug)}
                  >
                    <Trash2 size={13} aria-hidden />
                    {removeMod.isPending && removeMod.variables === mod.slug
                      ? 'Removing…'
                      : 'Remove'}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      <ListingReviews target="collection" slug={slug} isAuthor={isOwner} />
    </ListingDetailView>
  );
}
