import { collectionDetailSchema } from '@rsmm/schemas';
import { fetchEntity } from '../../../lib/entity';
import { CollectionDetailView } from './collection-detail-view';

export default async function CollectionDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const result = await fetchEntity<unknown>(`/api/collections/${slug}`);
  const parsed = result.state === 'ok' ? collectionDetailSchema.safeParse(result.data) : null;
  const initialData = parsed?.success ? parsed.data : undefined;
  return <CollectionDetailView key={slug} slug={slug} initialData={initialData} />;
}
