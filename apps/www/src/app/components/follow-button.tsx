'use client';
import { Button } from '@rsmm/ui';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, BellRing } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../lib/api';
import { useSession } from '../../lib/auth-client';

/** Follow / unfollow a mod to subscribe to new-version notifications. Hidden for
 *  logged-out users. Optimistic toggle; refetches the detail query on success. */
export function FollowButton({
  slug,
  initialFollowing,
  followerCount,
}: {
  slug: string;
  initialFollowing: boolean;
  followerCount: number;
}) {
  const { data: session } = useSession();
  const qc = useQueryClient();
  const [following, setFollowing] = useState(initialFollowing);
  const [count, setCount] = useState(followerCount);

  const toggle = useMutation({
    mutationFn: () => (following ? api.mods.unfollow(slug) : api.mods.follow(slug)),
    onMutate: () => {
      const next = !following;
      setFollowing(next);
      setCount((c) => c + (next ? 1 : -1));
    },
    onError: () => {
      // Revert optimistic update.
      const next = !following;
      setFollowing(!next);
      setCount((c) => c + (next ? -1 : 1));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mods', 'detail', slug] }),
  });

  if (!session) return null;

  return (
    <Button
      variant={following ? 'secondary' : 'outline'}
      size="sm"
      onClick={() => toggle.mutate()}
      disabled={toggle.isPending}
      title={following ? 'Unfollow — stop update alerts' : 'Follow — get notified of new versions'}
    >
      {following ? <BellRing className="mr-1.5 h-4 w-4" /> : <Bell className="mr-1.5 h-4 w-4" />}
      {following ? 'Following' : 'Follow'}
      {count > 0 && <span className="ml-1.5 text-xs text-muted-foreground">{count}</span>}
    </Button>
  );
}
