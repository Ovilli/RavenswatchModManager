import { ApiError } from '@rsmm/api-client';
import { useQuery } from '@tanstack/react-query';
import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { ArrowLeft, Plus, Trash2 } from 'lucide-react';
import {
  Button,
  Cover,
  CoverPlaceholder,
  Fleuron,
  Markdown,
  MonoTag,
  Panel,
  SectionHeader,
  StatPill,
} from '../components/chrome';
import { api } from '../lib/api';
import { inTauri } from '../lib/platform';
import { activeProfile, useApp } from '../store';

export const Route = createFileRoute('/mod/$slug')({
  component: ModDetailPage,
});

function ModDetailPage() {
  const { slug } = Route.useParams();
  const navigate = useNavigate();

  const { data, error, isLoading } = useQuery({
    queryKey: ['mods', 'detail', slug],
    queryFn: () => api.mods.get(slug),
    retry: (count, err) => (err instanceof ApiError && err.status === 404 ? false : count < 1),
    staleTime: 30_000,
    enabled: inTauri(),
  });

  const liveBySlug = useApp((s) => Object.values(s.localMods).find((m) => m.slug === slug));
  const installed = useApp((s) => s.installed);
  const profile = useApp(activeProfile);
  const installMod = useApp((s) => s.installMod);
  const uninstall = useApp((s) => s.uninstallMod);

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse" aria-busy="true">
        <div className="h-8 w-24 bg-oxblood/15 rounded" />
        <div className="aspect-[21/9] w-full bg-oxblood/20 rounded" />
        <div className="h-10 w-2/3 bg-oxblood/25 rounded" />
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <div className="md:col-span-2 space-y-3">
            <div className="h-4 w-full bg-oxblood/15 rounded" />
            <div className="h-4 w-5/6 bg-oxblood/15 rounded" />
            <div className="h-4 w-4/6 bg-oxblood/15 rounded" />
          </div>
          <div className="h-40 bg-oxblood/10 rounded" />
        </div>
      </div>
    );
  }

  const apiMod = data?.mod;
  const latestVersion = data?.versions?.[0];

  if (!apiMod && !liveBySlug) {
    return (
      <div className="space-y-4">
        <Button type="button" size="sm" onClick={() => navigate({ to: '/browse' })}>
          ← back
        </Button>
        <p className="font-serif-italic text-parchment">No mod matches “{slug}”.</p>
      </div>
    );
  }

  const name = apiMod?.name ?? liveBySlug?.name ?? slug;
  const author = apiMod?.author ?? liveBySlug?.author ?? 'unknown';
  const summary = apiMod?.summary ?? liveBySlug?.summary ?? '';
  const description = apiMod?.summary ?? liveBySlug?.description ?? '';
  const category = apiMod?.category ?? liveBySlug?.category ?? null;
  const tags = apiMod?.tags ?? liveBySlug?.tags ?? [];
  const rating = apiMod?.rating ?? null;
  const downloads = apiMod?.downloads ?? 0;
  const imageUrl = apiMod?.imageUrl ?? liveBySlug?.image ?? null;
  const apiLatest = apiMod?.latestVersion ?? null;
  const localVersion = liveBySlug?.version ?? null;
  const installedHere = liveBySlug ? installed.includes(liveBySlug.id) : false;
  const enabled = installedHere && liveBySlug ? !profile.disabled.has(liveBySlug.id) : false;
  const outdated = Boolean(localVersion && apiLatest && localVersion !== apiLatest);

  const markdown = liveBySlug?.markdown ?? `# ${name}\n\n${summary || description || ''}`;
  const sizeBytes = latestVersion?.sizeBytes ?? null;

  return (
    <div className="space-y-6">
      <Button type="button" size="sm" onClick={() => navigate({ to: '/browse' })}>
        <ArrowLeft className="h-3.5 w-3.5" /> back
      </Button>

      {imageUrl ? (
        <Cover
          src={imageUrl}
          alt={`${name} cover art`}
          caption={`${slug}-hero.png`}
          className="aspect-[21/9]"
        />
      ) : (
        <CoverPlaceholder caption={`${slug}-hero.png`} className="aspect-[21/9]" />
      )}

      <SectionHeader
        title={name}
        subtitle={`${author}${localVersion ? ` · v${localVersion}` : ''}${
          outdated && apiLatest
            ? ` → ${apiLatest}`
            : apiLatest && !localVersion
              ? ` · v${apiLatest}`
              : ''
        }`}
        right={
          installedHere && liveBySlug ? (
            <div className="flex items-center gap-2">
              <MonoTag tone={enabled ? 'crimson' : 'default'}>
                {enabled ? 'enabled' : 'disabled'}
              </MonoTag>
              <Button type="button" variant="danger" onClick={() => uninstall(liveBySlug.id)}>
                <Trash2 className="h-4 w-4" /> Uninstall
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="primary"
              onClick={() => installMod(apiMod?.id ?? liveBySlug?.id ?? slug)}
            >
              <Plus className="h-4 w-4" /> Install
            </Button>
          )
        }
      />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="space-y-4 md:col-span-2">
          <Panel>
            <h3 className="font-fraktur text-xl text-parchment mb-3">About</h3>
            <Fleuron />
            <Markdown source={markdown} className="mt-4" />
          </Panel>

          {liveBySlug?.changelog ? (
            <Panel>
              <h3 className="font-fraktur text-xl text-parchment mb-3">Changelog</h3>
              <Fleuron />
              <pre className="font-mono mt-4 whitespace-pre-wrap text-ash">
                {liveBySlug.changelog}
              </pre>
            </Panel>
          ) : null}
        </div>

        <aside className="space-y-4">
          <Panel>
            <h4 className="font-mono text-ash mb-3">Facts</h4>
            <dl className="space-y-2 text-sm">
              {category ? <Row k="Category" v={category} /> : null}
              {rating != null ? <Row k="Rating" v={`${rating.toFixed(1)} ★`} /> : null}
              <Row k="Downloads" v={downloads.toLocaleString()} />
              {sizeBytes != null ? (
                <Row k="Size" v={`${(sizeBytes / 1024 / 1024).toFixed(2)} MB`} />
              ) : null}
              {apiLatest ? <Row k="Latest" v={`v${apiLatest}`} /> : null}
            </dl>
          </Panel>

          {tags.length > 0 ? (
            <Panel>
              <h4 className="font-mono text-ash mb-3">Tags</h4>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((t) => (
                  <MonoTag key={t}>{t}</MonoTag>
                ))}
              </div>
            </Panel>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="font-mono text-ash">{k}</dt>
      <dd>
        <StatPill value={v} className="tracking-normal" />
      </dd>
    </div>
  );
}
