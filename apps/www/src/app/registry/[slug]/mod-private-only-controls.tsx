'use client';
import type { ModDetailResponse } from '@rsmm/api-client';
import { Button } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../lib/api';
import { useSession } from '../../../lib/auth-client';

export function ModPrivateOnlyControls({
  slug,
  privateOnly,
}: { slug: string; privateOnly: boolean }) {
  const { data: session } = useSession();
  const queryClient = useQueryClient();
  const whoami = useQuery({
    queryKey: ['me', 'whoami'],
    queryFn: () => api.me.whoami(),
    enabled: !!session,
  });
  const update = useMutation({
    mutationFn: () => api.moderation.setPrivateOnly(slug, !privateOnly),
    onSuccess: ({ tags }) => {
      queryClient.setQueryData<ModDetailResponse>(['mods', 'detail', slug], (current) =>
        current ? { ...current, mod: { ...current.mod, tags } } : current,
      );
      void queryClient.invalidateQueries({ queryKey: ['my-mod', slug] });
      void queryClient.invalidateQueries({ queryKey: ['registry'] });
    },
  });

  if (!session || !whoami.data?.isAdmin) return null;
  return (
    <div className="mod-private-only-controls">
      <p>RSMM admin</p>
      <Button
        variant="outline"
        size="sm"
        disabled={update.isPending}
        onClick={() => update.mutate()}
      >
        {update.isPending
          ? 'Saving…'
          : privateOnly
            ? 'Remove Private games only label'
            : 'Mark as Private games only'}
      </Button>
      {update.isError ? <p role="alert">Couldn’t update the label. Please try again.</p> : null}
    </div>
  );
}
