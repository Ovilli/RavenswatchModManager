'use client';

import { Check, Star, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

export interface RegistryFilterValue {
  category: string;
  status?: string;
  tags: string[];
  minRating: number;
  toggles: Record<string, boolean>;
}

export interface RegistryFilterOption {
  value: string;
  label: string;
  count?: number;
}

export function RegistryFilterDialog({
  value,
  categories,
  statuses = [],
  tags,
  ratings,
  toggles,
  onApply,
  onClose,
  onClear,
  labels = {},
}: {
  value: RegistryFilterValue;
  categories: RegistryFilterOption[];
  statuses?: RegistryFilterOption[];
  tags: RegistryFilterOption[];
  ratings: { value: number; label: string }[];
  toggles: { id: string; label: string; checked: boolean }[];
  onApply: (value: RegistryFilterValue) => void;
  onClose: () => void;
  onClear: () => RegistryFilterValue;
  labels?: {
    close?: string;
    title?: string;
    category?: string;
    status?: string;
    tags?: string;
    rating?: string;
    preferences?: string;
    all?: string;
    apply?: string;
    clear?: string;
  };
}) {
  const [draft, setDraft] = useState(value);
  const dialog = useRef<HTMLDialogElement>(null);

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

  const close = () => {
    dialog.current?.close();
    onClose();
  };
  const apply = () => {
    dialog.current?.close();
    onApply(draft);
  };

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
        if (event.target === event.currentTarget) close();
      }}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          apply();
        }}
      >
        <header className="registry-filter-header">
          <h2 id="registry-filter-title">{labels.title ?? 'Filters'}</h2>
          <button
            type="button"
            className="registry-icon-button"
            aria-label={labels.close ?? 'Close filters'}
            onClick={close}
          >
            <X size={20} aria-hidden />
          </button>
        </header>
        <div className="registry-filter-body">
          {statuses.length ? (
            <fieldset>
              <legend>{labels.status ?? 'Status'}</legend>
              <div className="registry-filter-options">
                {statuses.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className="registry-chip"
                    aria-pressed={draft.status === option.value}
                    onClick={() => setDraft({ ...draft, status: option.value })}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </fieldset>
          ) : null}
          <fieldset>
            <legend>{labels.category ?? 'Category'}</legend>
            <div className="registry-filter-options">
              {[{ value: '', label: labels.all ?? 'All mods' }, ...categories].map((option) => (
                <button
                  key={option.value || '_all'}
                  type="button"
                  className="registry-chip"
                  aria-pressed={draft.category === option.value}
                  onClick={() => setDraft({ ...draft, category: option.value })}
                >
                  {option.label}
                  {option.count != null ? (
                    <span className="registry-facet-count">{option.count}</span>
                  ) : null}
                </button>
              ))}
            </div>
          </fieldset>
          {tags.length ? (
            <fieldset>
              <legend>{labels.tags ?? 'Tags'}</legend>
              <div className="registry-filter-options">
                {tags.map((tag) => {
                  const selected = draft.tags.includes(tag.value);
                  return (
                    <button
                      key={tag.value}
                      type="button"
                      className="registry-chip"
                      aria-pressed={selected}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          tags: selected
                            ? draft.tags.filter((item) => item !== tag.value)
                            : [...draft.tags, tag.value],
                        })
                      }
                    >
                      {selected ? <Check size={14} aria-hidden /> : null}
                      {tag.label}
                      {tag.count != null ? (
                        <span className="registry-facet-count">{tag.count}</span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          ) : null}
          {ratings.length ? (
            <fieldset>
              <legend>{labels.rating ?? 'Rating'}</legend>
              <div className="registry-filter-options">
                {ratings.map((rating) => (
                  <button
                    key={rating.value}
                    type="button"
                    className="registry-chip"
                    aria-pressed={draft.minRating === rating.value}
                    onClick={() => setDraft({ ...draft, minRating: rating.value })}
                  >
                    {rating.value ? <Star size={15} aria-hidden /> : null}
                    {rating.label}
                  </button>
                ))}
              </div>
            </fieldset>
          ) : null}
          {toggles.length ? (
            <fieldset>
              <legend>{labels.preferences ?? 'Preferences'}</legend>
              {toggles.map((toggle) => (
                <label key={toggle.id} className="registry-filter-toggle">
                  <span>
                    <strong>{toggle.label}</strong>
                  </span>
                  <input
                    type="checkbox"
                    checked={draft.toggles[toggle.id] ?? toggle.checked}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        toggles: { ...draft.toggles, [toggle.id]: event.target.checked },
                      })
                    }
                  />
                </label>
              ))}
            </fieldset>
          ) : null}
        </div>
        <footer className="registry-filter-footer">
          <button type="button" className="registry-clear" onClick={() => setDraft(onClear())}>
            {labels.clear ?? 'Clear all'}
          </button>
          <button type="submit" className="registry-apply">
            {labels.apply ?? 'Show mods'}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
