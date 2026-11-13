'use client';

import { Check, Star, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import {
  EMPTY_REGISTRY_FILTERS,
  REGISTRY_CATEGORIES,
  REGISTRY_RATINGS,
  type RegistryFilters,
} from '../../../lib/registry-query';

export type RegistryFacet = { name: string; count: number };

export function RegistryFilterDialog({
  filters,
  categories,
  tags,
  onApply,
  onClose,
}: {
  filters: RegistryFilters;
  categories: RegistryFacet[];
  tags: RegistryFacet[];
  onApply: (filters: RegistryFilters) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(filters);
  const dialog = useRef<HTMLDialogElement>(null);
  const tagOptions = [...new Set([...tags.map((tag) => tag.name), ...draft.tags])];
  const close = () => {
    dialog.current?.close();
    onClose();
  };

  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      node?.close();
      document.body.style.overflow = overflow;
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className="registry-filter-dialog"
      aria-labelledby="registry-filter-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < bounds.left ||
          event.clientX > bounds.right ||
          event.clientY < bounds.top ||
          event.clientY > bounds.bottom
        )
          close();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          dialog.current?.close();
          onApply(draft);
        }}
      >
        <header className="registry-filter-header">
          <h2 id="registry-filter-title">Filters</h2>
          <button
            type="button"
            className="registry-icon-button"
            aria-label="Close filters"
            onClick={close}
          >
            <X size={20} aria-hidden />
          </button>
        </header>
        <div className="registry-filter-body">
          <fieldset>
            <legend>Category</legend>
            <p>What would you like to change?</p>
            <div className="registry-filter-options">
              <button
                type="button"
                className="registry-chip"
                aria-pressed={draft.category === 'all'}
                onClick={() => setDraft({ ...draft, category: 'all' })}
              >
                All mods
              </button>
              {REGISTRY_CATEGORIES.filter(
                (category) =>
                  !categories.length ||
                  categories.some((facet) => facet.name === category.id) ||
                  draft.category === category.id,
              ).map((category) => (
                <button
                  key={category.id}
                  type="button"
                  className="registry-chip"
                  aria-pressed={draft.category === category.id}
                  onClick={() =>
                    setDraft({
                      ...draft,
                      category: draft.category === category.id ? 'all' : category.id,
                    })
                  }
                >
                  {category.label}
                </button>
              ))}
            </div>
          </fieldset>
          {tagOptions.length ? (
            <fieldset>
              <legend>Tags</legend>
              <p>
                {draft.tags.length > 1
                  ? `Mods must match all ${draft.tags.length} selected tags.`
                  : 'Narrow it down by what a mod does.'}
              </p>
              <div className="registry-filter-options">
                {tagOptions.map((tag) => {
                  const selected = draft.tags.includes(tag);
                  const count = tags.find((facet) => facet.name === tag)?.count;
                  return (
                    <button
                      key={tag}
                      type="button"
                      className="registry-chip"
                      aria-pressed={selected}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          tags: selected
                            ? draft.tags.filter((value) => value !== tag)
                            : [...draft.tags, tag],
                        })
                      }
                    >
                      {selected ? <Check size={14} aria-hidden /> : null}
                      {tag}
                      {count != null ? <span className="registry-facet-count">{count}</span> : null}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          ) : null}
          <fieldset>
            <legend>Player rating</legend>
            <p>Choose a minimum rating from the community.</p>
            <div className="registry-filter-options">
              {REGISTRY_RATINGS.map((rating) => (
                <button
                  key={rating}
                  type="button"
                  className="registry-chip"
                  aria-pressed={draft.minRating === rating}
                  onClick={() => setDraft({ ...draft, minRating: rating })}
                >
                  {rating ? <Star size={15} aria-hidden /> : null}
                  {rating ? `${rating}+` : 'Any rating'}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend>Preferences</legend>
            <label className="registry-filter-toggle">
              <span>
                <strong>Featured mods only</strong>
                <span>Explore the highlighted community picks.</span>
              </span>
              <input
                type="checkbox"
                checked={draft.featuredOnly}
                onChange={(event) => setDraft({ ...draft, featuredOnly: event.target.checked })}
              />
            </label>
            <label className="registry-filter-toggle">
              <span>
                <strong>Include mature content</strong>
                <span>Show mods marked as NSFW alongside other results.</span>
              </span>
              <input
                type="checkbox"
                checked={draft.showNsfw}
                onChange={(event) => setDraft({ ...draft, showNsfw: event.target.checked })}
              />
            </label>
          </fieldset>
        </div>
        <footer className="registry-filter-footer">
          <button
            type="button"
            className="registry-clear"
            onClick={() => setDraft(EMPTY_REGISTRY_FILTERS)}
          >
            Clear all
          </button>
          <button type="submit" className="registry-apply">
            Show mods
          </button>
        </footer>
      </form>
    </dialog>
  );
}
