'use client';
import { Button, Input, Spinner } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { UserPlus, Users, X } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

/** Co-author management (owner only can add/remove; co-authors can view). Wires
 *  up the mod_authors table via /api/mods/:slug/authors. */
export function ModTeam({ slug }: { slug: string }) {
  const { data: session } = useSession();
  const qc = useQueryClient();
  const [handle, setHandle] = useState('');

  const team = useQuery({
    queryKey: ['mods', 'authors', slug],
    queryFn: () => api.mods.authors.list(slug),
    retry: false,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['mods', 'authors', slug] });
  const add = useMutation({
    mutationFn: (h: string) => api.mods.authors.add(slug, h),
    onSuccess: () => {
      setHandle('');
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (userId: string) => api.mods.authors.remove(slug, userId),
    onSuccess: invalidate,
  });

  const isOwner = !!session && team.data?.ownerId === session.user.id;

  return (
    <section className="grimoire-card space-y-4 p-5">
      <div className="flex items-center gap-2">
        <Users className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-lg font-semibold">Team</h2>
      </div>

      {team.isLoading ? (
        <Spinner />
      ) : team.isError ? (
        <p className="text-sm text-muted-foreground">Team unavailable.</p>
      ) : (
        <>
          <ul className="space-y-2">
            {team.data?.authors.length === 0 && (
              <li className="text-sm text-muted-foreground">No co-authors yet.</li>
            )}
            {team.data?.authors.map((a) => (
              <li key={a.userId} className="flex items-center justify-between text-sm">
                <span>
                  {a.name ?? a.handle ?? a.userId}
                  {a.handle && <span className="text-muted-foreground"> @{a.handle}</span>}
                  <span className="ml-2 text-xs text-muted-foreground">{a.role}</span>
                </span>
                {isOwner && (
                  <button
                    type="button"
                    aria-label="Remove co-author"
                    onClick={() => remove.mutate(a.userId)}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </li>
            ))}
          </ul>

          {isOwner && (
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (handle.trim()) add.mutate(handle.trim());
              }}
            >
              <Input
                placeholder="Add co-author by handle"
                value={handle}
                onChange={(e) => setHandle(e.target.value)}
              />
              <Button type="submit" size="sm" disabled={add.isPending || !handle.trim()}>
                <UserPlus className="mr-1.5 h-4 w-4" /> Add
              </Button>
            </form>
          )}
          {add.isError && (
            <p className="text-xs text-destructive">Could not add that user (check the handle).</p>
          )}
        </>
      )}
    </section>
  );
}
