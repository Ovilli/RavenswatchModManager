import { Link, createFileRoute } from '@tanstack/react-router';
import { ShieldCheck } from 'lucide-react';
import { useMemo } from 'react';
import { Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { activeProfile, detectConflicts, getMod, useApp } from '../store';

export const Route = createFileRoute('/conflicts')({
  component: ConflictsPage,
});

function ConflictsPage() {
  const profile = useApp(activeProfile);
  const toggle = useApp((s) => s.toggleMod);
  const conflicts = useMemo(() => detectConflicts(profile), [profile]);

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
                <h3 className="font-fraktur text-lg text-parchment">
                  Shared file
                </h3>
                <MonoTag tone="crimson">conflict</MonoTag>
              </div>
              <p className="font-mono mt-1 text-ash break-all">{c.path}</p>
              <Fleuron className="my-4" />

              <p className="font-serif-italic text-smoke mb-3">
                Choose which mod owns this file. The other will be disabled in this
                profile. You can re-enable it later.
              </p>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {c.modIds.map((id) => {
                  const mod = getMod(id);
                  if (!mod) return null;
                  const enabled = !profile.disabled.has(id);
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
                      <p className="font-serif-italic mt-2 text-sm text-smoke">
                        {mod.summary}
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          // make this one the keeper: enable it, disable the others
                          if (!enabled) toggle(id);
                          for (const other of c.modIds) {
                            if (other !== id && !profile.disabled.has(other)) {
                              toggle(other);
                            }
                          }
                        }}
                        className={`mt-3 w-full border px-3 py-2 transition-colors duration-150 ${
                          enabled
                            ? 'border-gilt/60 text-parchment'
                            : 'border-border text-ash hover:border-gilt/50 hover:text-parchment'
                        }`}
                      >
                        Keep this one
                      </button>
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
