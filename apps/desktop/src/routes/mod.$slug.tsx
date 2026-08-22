import { createFileRoute } from '@tanstack/react-router';
import { ModDetail } from '../components/mod-detail';

/**
 * The full-page store entry. The page itself is `ModDetail`, which Browse also
 * renders in its split view — see that component for why it is not defined
 * here.
 */
export const Route = createFileRoute('/mod/$slug')({
  component: ModDetailRoute,
});

function ModDetailRoute() {
  const { slug } = Route.useParams();
  return <ModDetail slug={slug} />;
}
