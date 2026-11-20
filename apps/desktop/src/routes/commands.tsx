import { createFileRoute, redirect } from '@tanstack/react-router';

export const Route = createFileRoute('/commands')({
  beforeLoad: () => {
    throw redirect({
      to: '/settings',
      search: { tab: 'diagnostics' },
      hash: 'commands',
      replace: true,
    });
  },
});
