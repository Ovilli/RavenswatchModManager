'use client';
import { Button } from './button';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { reviewText, type ReviewTextOptions } from '../lib/review-text';

/**
 * The owner's public reply under a review (mods, collections, guides), with
 * reply / edit / delete controls when `canReply`. `queryKey` is the review
 * list to refetch after a change.
 */
export function ReviewReplyBlock({
  review,
  canReply,
  queryKey,
  onSave,
  onDelete,
  t = reviewText,
  locale = 'en-US',
}: {
  review: { ownerReply?: string | null; ownerReplyAt?: string | null };
  canReply: boolean;
  queryKey: readonly unknown[];
  onSave: (text: string) => Promise<unknown>;
  onDelete: () => Promise<unknown>;
} & ReviewTextOptions) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(review.ownerReply ?? '');
  const refresh = () => qc.invalidateQueries({ queryKey });
  const save = useMutation({
    mutationFn: () => onSave(text.trim()),
    onSuccess: async () => {
      setEditing(false);
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: onDelete,
    onSuccess: async () => {
      setText('');
      await refresh();
    },
  });

  if (editing) {
    return (
      <div className="mt-3 space-y-2 border-l-2 border-gilt/50 pl-3">
        <textarea
          aria-label={t('Reply to review')}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('Reply publicly to this review…')}
          maxLength={2000}
          rows={3}
          className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        {save.isError ? (
          <p role="alert" className="text-xs text-crimson">
            {save.error instanceof Error ? save.error.message : t('Failed to save reply')}
          </p>
        ) : null}
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            onClick={() => save.mutate()}
            disabled={save.isPending || !text.trim()}
          >
            {save.isPending ? t('Saving…') : t('Post reply')}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
            {t('Cancel')}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <>
      {remove.isError ? (
        <p role="alert" className="mt-2 text-xs text-crimson">
          {t('Your reply couldn’t be deleted. Please try again.')}
        </p>
      ) : null}
      {review.ownerReply ? (
        <div className="mt-3 border-l-2 border-gilt/50 pl-3">
          <p className="font-mono text-xs uppercase tracking-wide text-gilt">
            {t('Author reply')}
            {review.ownerReplyAt
              ? ` · ${new Date(review.ownerReplyAt).toLocaleDateString(locale)}`
              : ''}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
            {review.ownerReply}
          </p>
        </div>
      ) : null}
      {canReply ? (
        <div className="mt-2 flex gap-3 text-xs">
          <button
            type="button"
            className="text-muted-foreground underline-offset-2 hover:text-gilt hover:underline"
            disabled={remove.isPending}
            onClick={() => {
              save.reset();
              remove.reset();
              setText(review.ownerReply ?? '');
              setEditing(true);
            }}
          >
            {review.ownerReply ? t('Edit reply') : t('Reply')}
          </button>
          {review.ownerReply ? (
            <button
              type="button"
              className="text-muted-foreground underline-offset-2 hover:text-crimson hover:underline"
              disabled={remove.isPending || save.isPending}
              onClick={() => remove.mutate()}
            >
              {t('Delete reply')}
            </button>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
