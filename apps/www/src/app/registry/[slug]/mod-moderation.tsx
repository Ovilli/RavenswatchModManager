'use client';
import { Badge, Button, Spinner } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { EyeOff, RotateCcw, ShieldAlert, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../../lib/api';

type ThreadItem = Awaited<ReturnType<typeof api.mods.moderationThread>>['items'][number];
type TakedownStatus = 'active' | 'hidden' | 'removed';

const STATUS_LABEL: Record<string, string> = {
  active: 'Listed',
  hidden: 'Hidden',
  removed: 'Removed',
};

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
];
function timeAgo(iso: string): string {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return 'just now';
}

function Author({ item }: { item: ThreadItem }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-semibold text-parchment">
      {item.authorName ?? (item.fromModerator ? 'A moderator' : 'Deleted user')}
      {item.fromModerator ? (
        <Badge variant="outline" className="border-gilt/50 text-gilt">
          Moderator
        </Badge>
      ) : null}
    </span>
  );
}

function Entry({ item }: { item: ThreadItem }) {
  const when = (
    <time
      dateTime={item.createdAt}
      title={new Date(item.createdAt).toLocaleString()}
      className="text-xs text-muted-foreground"
    >
      {timeAgo(item.createdAt)}
    </time>
  );
  if (item.kind === 'status') {
    return (
      <li className="flex gap-3 text-sm">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-gilt/80" aria-hidden />
        <div className="min-w-0">
          <p className="text-muted-foreground">
            <Author item={item} /> changed the status
            {item.fromStatus ? (
              <>
                {' '}
                from <strong>{STATUS_LABEL[item.fromStatus] ?? item.fromStatus}</strong>
              </>
            ) : null}{' '}
            to <strong>{STATUS_LABEL[item.toStatus ?? ''] ?? item.toStatus}</strong>. {when}
          </p>
          {item.body ? (
            <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-gilt/40 bg-background/40 px-3 py-2 text-parchment/90">
              {item.body}
            </blockquote>
          ) : null}
        </div>
      </li>
    );
  }
  return (
    <li
      className={`rounded-md border p-3 text-sm ${
        item.fromModerator ? 'border-gilt/40 bg-gilt/5' : 'border-border bg-background/40'
      }`}
    >
      <p className="flex flex-wrap items-center gap-2">
        <Author item={item} /> {when}
      </p>
      <p className="mt-1.5 whitespace-pre-wrap text-parchment/90">{item.body}</p>
    </li>
  );
}

/**
 * Private moderation thread for a mod's team and the moderators: every status
 * change (hide / remove / restore, with its reason) and messages from either
 * side. Rendered only for viewers the API lets edit the listing (team + admins);
 * the API enforces the same rule.
 */
export function ModModeration({
  slug,
  takedownStatus,
}: {
  slug: string;
  takedownStatus: TakedownStatus;
}) {
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [reason, setReason] = useState('');
  const thread = useQuery({
    queryKey: ['mods', 'moderation', slug],
    queryFn: () => api.mods.moderationThread(slug),
    retry: false,
  });
  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['mods', 'moderation', slug] }),
      qc.invalidateQueries({ queryKey: ['mods', 'detail', slug] }),
      qc.invalidateQueries({ queryKey: ['admin'] }),
    ]);
  };
  const send = useMutation({
    mutationFn: () => api.mods.sendModerationMessage(slug, text.trim()),
    onSuccess: async () => {
      setText('');
      await refresh();
    },
  });
  const setStatus = useMutation({
    mutationFn: (status: TakedownStatus) =>
      api.moderation.takedown(slug, {
        takedownStatus: status,
        reason: status === 'active' ? null : reason.trim() || null,
      }),
    onSuccess: async () => {
      setReason('');
      await refresh();
    },
  });

  // Notifications link to #moderation, but this section only renders after the
  // client fetch, so the browser's own jump to the hash has already happened.
  const sectionRef = useRef<HTMLElement>(null);
  const scrolled = useRef(false);
  useEffect(() => {
    if (scrolled.current || !thread.data || window.location.hash !== '#moderation') return;
    scrolled.current = true;
    sectionRef.current?.scrollIntoView();
  }, [thread.data]);

  const moderator = thread.data?.viewerIsModerator ?? false;
  const items = thread.data?.items ?? [];
  const failure = send.error ?? setStatus.error;
  const busy = send.isPending || setStatus.isPending;

  return (
    <section
      ref={sectionRef}
      id="moderation"
      className="mod-section"
      style={{ borderTop: '1px solid var(--mod-rule)' }}
      aria-labelledby="mod-moderation-heading"
    >
      <h2 id="mod-moderation-heading">Moderation</h2>
      <div className="space-y-5">
        <div className="space-y-1 text-sm text-muted-foreground">
          <p>
            <strong className="text-parchment">Moderation messages.</strong>{' '}
            {moderator
              ? 'A private thread with this mod’s authors. Only they and the moderators can see it. Your messages notify the authors.'
              : 'A private conversation with the RSMM moderators. They may message you here about issues with this mod. Only you, your co-authors and the moderators can see it.'}
          </p>
          {!moderator ? (
            <p>
              Moderators can’t help with most support questions, and messages you send here don’t
              notify them.
            </p>
          ) : null}
          <p>
            Current status:{' '}
            <strong className={takedownStatus === 'active' ? 'text-parchment' : 'text-destructive'}>
              {STATUS_LABEL[takedownStatus]}
            </strong>
          </p>
        </div>

        {thread.isLoading ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : thread.isError ? (
          <p className="text-sm text-destructive">Couldn’t load the moderation thread.</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No moderation activity yet.</p>
        ) : (
          <ol className="space-y-4">
            {items.map((item) => (
              <Entry key={item.id} item={item} />
            ))}
          </ol>
        )}

        {failure ? (
          <p role="alert" className="text-sm text-destructive">
            {failure instanceof Error ? failure.message : String(failure)}
          </p>
        ) : null}

        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) send.mutate();
          }}
        >
          <textarea
            aria-label="Message"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={moderator ? 'Message the authors…' : 'Message the moderators…'}
            maxLength={4000}
            rows={3}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <Button type="submit" size="sm" disabled={busy || !text.trim()}>
            {send.isPending ? 'Sending…' : 'Send'}
          </Button>
        </form>

        {moderator ? (
          <div className="space-y-2 border-t border-border/50 pt-4">
            <p className="text-sm font-semibold text-parchment">Change status</p>
            {takedownStatus !== 'active' ? null : (
              <textarea
                aria-label="Reason shown to the authors"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Reason shown to the authors (recommended)"
                maxLength={2000}
                rows={2}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            )}
            <div className="flex flex-wrap gap-2">
              {takedownStatus === 'active' ? (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1.5"
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm('Hide this mod? It disappears from the public registry.')
                      ) {
                        setStatus.mutate('hidden');
                      }
                    }}
                  >
                    <EyeOff className="h-3.5 w-3.5" aria-hidden /> Hide
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    className="gap-1.5"
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm('Remove this mod? It disappears from the public registry.')
                      ) {
                        setStatus.mutate('removed');
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden /> Remove
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm('Restore this mod? It goes back on the public registry.')) {
                      setStatus.mutate('active');
                    }
                  }}
                >
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Restore
                </Button>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
