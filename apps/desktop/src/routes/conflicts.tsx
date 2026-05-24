import { Link, createFileRoute } from '@tanstack/react-router';
import { ShieldCheck } from 'lucide-react';
import { useMemo } from 'react';
import { Button, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { activeProfile, detectConflicts, getMod, isEnabledIn, useApp } from '../store';

export const Route = createFileRoute('/conflicts')({
  component: ConflictsPage,
});

function ConflictsPage() {
  const profile = useApp(activeProfile);
  const toggle = useApp((s) => s.toggleMod);
  const conflicts = useMemo(() => detectConflicts(profile), [profile]);
  const conflictCountByMod = useMemo(() => {
    const counts = new Map<string, number>();
    for (const conflict of conflicts) {
      for (const modId of conflict.modIds) {
        counts.set(modId, (counts.get(modId) ?? 0) + 1);
      }
    }
    return counts;
  }, [conflicts]);

  if (conflicts.length === 0) {
    return (
      <div className="space-y-6">
        <SectionHeader title="Conflicts" subtitle="Two mods writing the same file." />
        <Panel className="flex flex-col items-center gap-3 py-12 text-center">
          <ShieldCheck className="h-8 w-8 text-crimson" />
          <p className="font-fraktur text-2xl text-parchment">All quiet</p>
          <p className="font-serif-italic text-ash">
            No enabled mod in {profile.name} touches the same file as another.
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
        {conflicts.map((c) => (
          <li key={c.path}>
            <Panel>
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="font-fraktur text-lg text-parchment">Shared file</h3>
                <div className="flex items-center gap-2">
                  <MonoTag tone="crimson">conflict</MonoTag>
                  <MonoTag tone="gilt">{c.modIds.length} mods</MonoTag>
                </div>
              </div>
              <p className="font-mono mt-1 text-ash break-all">{c.path}</p>
              <Fleuron className="my-4" />

              <p className="font-serif-italic text-smoke mb-3">
                Why this conflicts: each listed mod writes this same file. Keep one enabled and
                disable the others.
              </p>

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
                        <MonoTag tone="gilt">
                          {conflictCountByMod.get(id) ?? 0} file{(conflictCountByMod.get(id) ?? 0) === 1 ? '' : 's'}
                        </MonoTag>
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
                                const p = state.profiles.find((x) => x.id === state.activeProfileId);
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
        ))}
      </ul>
    </div>
  );
}
