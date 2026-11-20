import { createFileRoute } from '@tanstack/react-router';
import { ModDetail } from '../components/mod-detail';

/** The full-page destination for Browse and Library mod listings. */
export const Route = createFileRoute('/mod/$slug')({
  component: ModDetailRoute,
});

function ModDetailRoute() {
  const { slug } = Route.useParams();
  return <ModDetail slug={slug} />;
}
