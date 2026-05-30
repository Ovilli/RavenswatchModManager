import { useQuery } from '@tanstack/react-query';
import { Link, createFileRoute } from '@tanstack/react-router';
import { AlertTriangle, FileType, ShieldCheck, Swords } from 'lucide-react';
import { Button, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { type ConflictEntry, getConflicts } from '../lib/rsmm';
import { activeProfile, getMod, isEnabledIn, useApp } from '../store';

export const Route = createFileRoute('/conflicts')({
  component: ConflictsPage,
});

const TYPE_META: Record<
  ConflictEntry['type'],
  { icon: typeof FileType; label: string; explanation: string }
> = {
  file: {
    icon: FileType,
    label: 'Same file',
    explanation: 'Each listed mod writes this same file. Keep one enabled and disable the others.',
  },
  patch: {
    icon: Swords,
    label: 'Patch conflict',
    explanation:
      'Each listed mod patches the same field with a different value. Keep one enabled and disable the others.',
  },
  manifest: {
    icon: AlertTriangle,
    label: 'Declared conflict',
    explanation:
      'These mods declare each other as incompatible via manifest.conflicts. They cannot be enabled at the same time.',
  },
};

function ConflictsPage() {
  const profile = useApp(activeProfile);
  const toggle = useApp((s) => s.toggleMod);
  const { data } = useQuery({
    queryKey: ['conflicts'],
    queryFn: getConflicts,
  });
  const conflicts = data ?? [];

  if (conflicts.length === 0) {
    return (
      <div className="space-y-6">
        <SectionHeader
          title="Conflicts"
          subtitle="File, patch, and manifest conflicts among enabled mods."
        />
        <Panel className="flex flex-col items-center gap-3 py-12 text-center">
          <ShieldCheck className="h-8 w-8 text-crimson" />
          <p className="font-fraktur text-2xl text-parchment">All quiet</p>
          <p className="font-serif-italic text-ash">
            No enabled mod in {profile.name} conflicts with another.
          </p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Conflicts"
        subtitle={`${conflicts.length} ${
          conflicts.length === 1 ? 'collision' : 'collisions'
        } among enabled mods in ${profile.name}.`}
      />

      <ul className="space-y-4">
        {conflicts.map((c, i) => {
          const meta = TYPE_META[c.type];
          const Icon = meta.icon;
          const key = c.type === 'file' ? c.path : `${c.type}-${i}`;
          return (
            <li key={key}>
              <Panel>
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="font-fraktur text-lg text-parchment">{meta.label}</h3>
                  <div className="flex items-center gap-2">
                    <MonoTag tone="crimson">conflict</MonoTag>
                    <MonoTag tone="gilt">{c.modIds.length} mods</MonoTag>
                  </div>
                </div>
                {c.type === 'file' && c.path ? (
                  <p className="font-mono mt-1 text-ash break-all">{c.path}</p>
                ) : c.type === 'patch' && c.field ? (
                  <p className="font-mono mt-1 text-ash break-all">
                    {c.patchKind}: {c.field}
                  </p>
                ) : null}
                <Fleuron className="my-4" />

                <p className="font-serif-italic text-smoke mb-3">{meta.explanation}</p>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  {c.modIds.map((id) => {
                    const mod = getMod(id);
                    if (!mod) return null;
                    const enabled = isEnabledIn(profile, id);
                    return (
                      <div
                        key={id}
                        className={`border p-4 ${
                          enabled
                            ? 'border-crimson/70 bg-crimson/10'
                            : 'border-border bg-pitch/40 opacity-70'
                        }`}
                      >
                        <Link
                          to="/mod/$slug"
                          params={{ slug: mod.slug }}
                          className="font-serif-italic text-lg text-parchment hover:text-gilt"
                        >
                          {mod.name}
                        </Link>
                        <p className="font-mono mt-1 text-ash">
                          {mod.author} · v{mod.version}
                        </p>
                        <p className="font-serif-italic mt-2 text-sm text-smoke">{mod.summary}</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <MonoTag tone={enabled ? 'crimson' : 'default'}>
                            {enabled ? 'enabled' : 'disabled'}
                          </MonoTag>
                          <Icon className="h-4 w-4 text-crimson" />
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant={enabled ? 'danger' : 'primary'}
                            onClick={() => {
                              if (!enabled) toggle(id);
                              for (const other of c.modIds) {
                                if (other !== id) {
                                  const state = useApp.getState();
                                  const p = state.profiles.find(
                                    (x) => x.id === state.activeProfileId,
                                  );
                                  if (p && isEnabledIn(p, other)) {
                                    state.toggleMod(other);
                                  }
                                }
                              }
                            }}
                          >
                            {enabled ? 'Keep this one' : 'Enable this one'}
                          </Button>
                          {enabled ? (
                            <Button type="button" size="sm" onClick={() => toggle(id)}>
                              Disable this mod
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Panel>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
