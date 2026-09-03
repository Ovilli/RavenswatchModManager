import { useQuery } from '@tanstack/react-query';
import { Link, createFileRoute } from '@tanstack/react-router';
import { AlertTriangle, FileType, ShieldCheck, Swords } from 'lucide-react';
import { Button, CopyButton, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { useModToggle } from '../components/use-mod-toggle';
import { msg } from '../lib/i18n';
import { useT } from '../lib/i18n-react';
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
    label: msg('Same file'),
    explanation: msg(
      'Each listed mod writes this same file. Keep one enabled and disable the others.',
    ),
  },
  patch: {
    icon: Swords,
    label: msg('Patch conflict'),
    explanation: msg(
      'Each listed mod patches the same field with a different value. Keep one enabled and disable the others.',
    ),
  },
  manifest: {
    icon: AlertTriangle,
    label: msg('Declared conflict'),
    explanation: msg(
      'These mods declare each other as incompatible via manifest.conflicts. They cannot be enabled at the same time.',
    ),
  },
};

function ConflictsPage() {
  const t = useT();
  const profile = useApp(activeProfile);
  // The shared guard, not the raw store action: disabling a mod others depend
  // on has to raise the broken-dependency prompt here too. Going straight to
  // `toggleMod` meant the Library and the mod page warned and this screen did
  // not, which is the screen most likely to disable something.
  const { enableMods, disableMods } = useModToggle();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['conflicts'],
    queryFn: getConflicts,
  });
  const conflicts = data ?? [];

  // Resolve a conflict group in ONE call per direction rather than a toggle
  // per mod: `toggle` raises the dependency prompt itself, so a loop over it
  // would ask once per mod and each answer would be judged against the same
  // pre-prompt profile snapshot. The batch form asks once and applies once.
  const keepOnly = (keepId: string, group: string[]) => {
    if (!isEnabledIn(profile, keepId)) void enableMods([keepId]);
    const others = group.filter((id) => id !== keepId && isEnabledIn(profile, id));
    if (others.length) void disableMods(others);
  };
  const disableAll = (group: string[]) => {
    const on = group.filter((id) => isEnabledIn(profile, id));
    if (on.length) void disableMods(on);
  };

  // An empty list is not the same answer as "we have not been told yet" or
  // "we could not find out". Both used to render the reassuring "All quiet"
  // panel below — on the one screen whose entire job is to warn you.
  if (isLoading || isError) {
    return (
      <div className="space-y-6">
        <SectionHeader
          title={t('Conflicts')}
          subtitle={t('File, patch, and manifest conflicts among enabled mods.')}
        />
        {isError ? (
          <Panel className="border-crimson">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-crimson" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="font-fraktur text-xl text-parchment">
                  {t('Could not check for conflicts')}
                </p>
                <p className="font-data mt-2 break-words text-sm text-ash">
                  {error instanceof Error ? error.message : String(error)}
                </p>
                <div className="mt-4 flex items-center gap-2">
                  <Button type="button" size="sm" onClick={() => void refetch()}>
                    {t('Try again')}
                  </Button>
                  <CopyButton value={error instanceof Error ? error.message : String(error)} />
                </div>
              </div>
            </div>
          </Panel>
        ) : (
          <Panel className="flex flex-col items-center gap-3 py-12 text-center">
            <p className="font-serif-italic text-ash">{t('Checking for conflicts…')}</p>
          </Panel>
        )}
      </div>
    );
  }

  if (conflicts.length === 0) {
    return (
      <div className="space-y-6">
        <SectionHeader
          title={t('Conflicts')}
          subtitle={t('File, patch, and manifest conflicts among enabled mods.')}
        />
        <Panel className="flex flex-col items-center gap-3 py-12 text-center">
          <ShieldCheck className="h-8 w-8 text-crimson" />
          <p className="font-fraktur text-2xl text-parchment">{t('All quiet')}</p>
          <p className="font-serif-italic text-ash">
            {t('No enabled mod in {profile} conflicts with another.', { profile: profile.name })}
          </p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t('Conflicts')}
        subtitle={t.n(
          conflicts.length,
          '{n} collision among enabled mods in {profile}.',
          '{n} collisions among enabled mods in {profile}.',
          { profile: profile.name },
        )}
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
                  <h3 className="font-fraktur text-lg text-parchment">{t(meta.label)}</h3>
                  <div className="flex items-center gap-2">
                    <MonoTag tone="crimson">{t('conflict')}</MonoTag>
                    <MonoTag tone="gilt">{t.n(c.modIds.length, '{n} mod', '{n} mods')}</MonoTag>
                    {c.modIds.some((id) => isEnabledIn(profile, id)) ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="danger"
                        onClick={() => disableAll(c.modIds)}
                      >
                        {t('Disable all')}
                      </Button>
                    ) : null}
                  </div>
                </div>
                {c.type === 'file' && c.path ? (
                  <p className="font-data mt-1 text-ash break-all">{c.path}</p>
                ) : c.type === 'patch' && c.field ? (
                  <p className="font-mono mt-1 text-ash break-all">
                    {c.patchKind}: {c.field}
                  </p>
                ) : null}
                <Fleuron className="my-4" />

                <p className="font-serif-italic text-smoke mb-3">{t(meta.explanation)}</p>

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
                            {enabled ? t('enabled') : t('disabled')}
                          </MonoTag>
                          <Icon className="h-4 w-4 text-crimson" />
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant={enabled ? 'danger' : 'primary'}
                            onClick={() => keepOnly(id, c.modIds)}
                          >
                            {enabled ? t('Keep this one') : t('Enable this one')}
                          </Button>
                          {enabled ? (
                            <Button type="button" size="sm" onClick={() => void disableMods([id])}>
                              {t('Disable this mod')}
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
