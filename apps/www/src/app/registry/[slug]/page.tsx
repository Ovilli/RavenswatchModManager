import { modDetailResponseSchema } from '@rsmm/api-client';
import { renderMarkdown } from '../../../lib/markdown';
import { getLatestRelease } from '../../../lib/releases';
import { fetchViewerEntity } from '../../../lib/viewer-entity';
import { ModDetailView } from './mod-detail-view';

export default async function ModDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [result, release] = await Promise.all([
    fetchViewerEntity<unknown>(`/api/mods/${slug}`),
    getLatestRelease(),
  ]);
  const parsed = result.state === 'ok' ? modDetailResponseSchema.safeParse(result.data) : null;
  const initialData = parsed?.success ? parsed.data : undefined;
  return (
    <ModDetailView
      key={slug}
      slug={slug}
      initialData={initialData}
      descriptionHtml={renderMarkdown(initialData?.mod.description)}
      managerDownloads={{ windows: release.windows, linux: release.linux }}
    />
  );
}
