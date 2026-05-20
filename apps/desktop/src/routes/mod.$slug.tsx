import { Link, createFileRoute, useNavigate } from '@tanstack/react-router';
import { ArrowLeft, Check, Plus, Trash2 } from 'lucide-react';
import { Button, Cover, CoverPlaceholder, Fleuron, Markdown, MonoTag, Panel, SectionHeader, StatPill } from '../components/chrome';
import { MOCK_MODS } from '../data/mock-mods';
import { activeProfile, useApp } from '../store';

export const Route = createFileRoute('/mod/$slug')({
  component: ModDetailPage,
});

function ModDetailPage() {
  const { slug } = Route.useParams();
  const navigate = useNavigate();
  const mod = MOCK_MODS.find((m) => m.slug === slug);
  const installed = useApp((s) => s.installed);
  const profile = useApp(activeProfile);
  const installMod = useApp((s) => s.installMod);
  const uninstall = useApp((s) => s.uninstallMod);

  if (!mod) {
    return (
      <div className="space-y-4">
        <Button
          type="button"
          size="sm"
          onClick={() => navigate({ to: '/browse' })}
        >
          ← back
        </Button>
        <p className="font-serif-italic text-parchment">No mod matches “{slug}”.</p>
      </div>
    );
  }

  const here = installed.includes(mod.id);
  const enabled = here && !profile.disabled.has(mod.id);
  const outdated = mod.version !== mod.latestVersion;

  return (
    <div className="space-y-6">
      <Button
        type="button"
        size="sm"
        onClick={() => history.back()}
      >
        <ArrowLeft className="h-3.5 w-3.5" /> back
      </Button>

      <Cover
        src={mod.image}
        alt={`${mod.name} cover art`}
        caption={`${mod.slug}-hero.png`}
        className="aspect-[21/9]"
      />

      <SectionHeader
        title={mod.name}
        subtitle={`${mod.author} · v${mod.version} ${
          outdated ? `→ ${mod.latestVersion}` : ''
        }`}
        right={
          here ? (
            <div className="flex items-center gap-2">
              <MonoTag tone={enabled ? 'crimson' : 'default'}>
                {enabled ? 'enabled' : 'disabled'}
              </MonoTag>
              <Button
                type="button"
                variant="danger"
                onClick={() => uninstall(mod.id)}
              >
                <Trash2 className="h-4 w-4" /> Uninstall
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="primary"
              onClick={() => installMod(mod.id)}
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
            <Markdown source={mod.markdown} className="mt-4" />
          </Panel>

          <Panel>
            <h3 className="font-fraktur text-xl text-parchment mb-3">Changelog</h3>
            <Fleuron />
            <pre className="font-mono mt-4 whitespace-pre-wrap text-ash">
              {mod.changelog}
            </pre>
          </Panel>

          <Panel>
            <h3 className="font-fraktur text-xl text-parchment mb-3">Screenshots</h3>
            <Fleuron />
            <div className="mt-4 grid grid-cols-2 gap-3">
              <CoverPlaceholder caption="01.png" className="aspect-[4/3]" />
              <CoverPlaceholder caption="02.png" className="aspect-[4/3]" />
            </div>
          </Panel>
        </div>

        <aside className="space-y-4">
          <Panel>
            <h4 className="font-mono text-ash mb-3">Facts</h4>
            <dl className="space-y-2 text-sm">
              <Row k="Category" v={mod.category} />
              <Row k="Rating" v={`${mod.rating.toFixed(1)} ★`} />
              <Row k="Downloads" v={mod.downloads.toLocaleString()} />
              <Row k="Size" v={`${(mod.sizeKb / 1024).toFixed(2)} MB`} />
              <Row k="Game build" v={mod.gameBuild} />
            </dl>
          </Panel>

          <Panel>
            <h4 className="font-mono text-ash mb-3">Tags</h4>
            <div className="flex flex-wrap gap-1.5">
              {mod.tags.map((t) => (
                <MonoTag key={t}>{t}</MonoTag>
              ))}
            </div>
          </Panel>

          <Panel>
            <h4 className="font-mono text-ash mb-3">Dependencies</h4>
            {mod.dependencies.length === 0 ? (
              <p className="font-serif-italic text-ash">None.</p>
            ) : (
              <ul className="space-y-1">
                {mod.dependencies.map((d) => {
                  const dep = MOCK_MODS.find((x) => x.id === d);
                  return (
                    <li key={d}>
                      <Link
                        to="/mod/$slug"
                        params={{ slug: dep?.slug ?? d }}
                        className="font-serif-italic text-parchment hover:text-gilt"
                      >
                        {dep?.name ?? d}
                      </Link>
                      {installed.includes(d) ? (
                        <Check className="ml-1.5 inline h-3.5 w-3.5 text-crimson" />
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <Panel>
            <h4 className="font-mono text-ash mb-3">Writes</h4>
            <ul className="font-mono space-y-1 text-ash">
              {mod.writes.map((w) => (
                <li key={w} className="truncate" title={w}>
                  {w}
                </li>
              ))}
            </ul>
          </Panel>
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
