import { createFileRoute, redirect } from '@tanstack/react-router';

export const Route = createFileRoute('/log')({
  beforeLoad: () => {
    throw redirect({
      to: '/settings',
      search: { tab: 'diagnostics' },
      hash: 'game-log',
      replace: true,
    });
  },
});
