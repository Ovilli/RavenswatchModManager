import { createFileRoute, redirect } from '@tanstack/react-router';

/**
 * About moved into Settings as a tab — one place for "how is this thing
 * configured, and what is it". The route is kept as a redirect rather than
 * deleted so an older link, or anyone's muscle memory, still lands on the
 * content instead of a blank route.
 */
export const Route = createFileRoute('/about')({
  beforeLoad: () => {
    throw redirect({ to: '/settings', search: { tab: 'about' }, replace: true });
  },
});
