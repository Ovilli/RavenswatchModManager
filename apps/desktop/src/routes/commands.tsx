import { createFileRoute } from '@tanstack/react-router';
import {
  CheckCircle2,
  Loader2,
  Play,
  RotateCcw,
  ServerCrash,
  ShieldCheck,
  Stethoscope,
  Terminal,
  Wrench,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { CommandResult, type CommandResultKind } from '../components/command-result';
import { useLaunch } from '../components/launch';
import { useDialog, useToast } from '../components/toast';
import { explainError } from '../lib/errors';
import { useT } from '../lib/i18n-react';
import { applyMods, build, doctor, listLocalMods, restoreAll } from '../lib/rsmm';

type CommandStatus = 'idle' | 'running' | 'success' | 'error';

interface CommandEntry {
  id: string;
  label: string;
  /** Which renderer the result gets — the bridge returns raw JSON, and only
   * the command that asked for it knows what shape to expect. */
  kind: CommandResultKind;
  status: CommandStatus;
  startedAt: number;
  finishedAt?: number;
  result?: unknown;
  error?: string;
}

interface CommandSpec {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  tone: 'default' | 'primary' | 'gilt' | 'danger';
  kind: CommandResultKind;
  /** Safe to run while the game is up — read-only inspection. Everything
   * else writes to the install and must wait for the session to end. */
  readOnly?: boolean;
  /** Ask before running. Set for anything that rewrites the game install:
   *  these are single-click buttons, and "Restore originals" undoes every
   *  applied mod. A read-only inspection needs no prompt. */
  confirmBody?: string;
  run: () => Promise<unknown>;
}

export const Route = createFileRoute('/commands')({
  component: CommandsPage,
});

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function formatClock(ms: number, locale: string): string {
  return new Date(ms).toLocaleTimeString(locale);
}

function formatDuration(start: number, end?: number): string | null {
  if (!end) return null;
  const s = (end - start) / 1000;
  return s < 1 ? `${Math.max(1, Math.round(end - start))}ms` : `${s.toFixed(1)}s`;
}

function CommandsPage() {
  const t = useT();
  const [entries, setEntries] = useState<CommandEntry[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const toast = useToast();
  const dialog = useDialog();
  // Launching goes through the shared controller so the restore watcher and
  // the "quit with active overrides?" guard apply here too.
  const { launch, busy: launchBusy } = useLaunch();

  const commands = useMemo<CommandSpec[]>(
    () => [
      {
        id: 'list',
        label: t('List local mods'),
        description: t('Show every mod currently installed in the local mods folder.'),
        icon: <Terminal className="h-4 w-4" aria-hidden="true" />,
        tone: 'default',
        kind: 'mods',
        readOnly: true,
        run: () => listLocalMods(),
      },
      {
        id: 'doctor',
        label: t('Doctor'),
        description: t('Run the health check for paths, loader, and core setup.'),
        icon: <ShieldCheck className="h-4 w-4" aria-hidden="true" />,
        tone: 'gilt',
        kind: 'doctor',
        readOnly: true,
        run: () => doctor(),
      },
      {
        id: 'doctor-fix',
        label: t('Doctor + repair'),
        description: t('Run the health check, then apply the safe automated repairs it finds.'),
        icon: <Stethoscope className="h-4 w-4" aria-hidden="true" />,
        tone: 'gilt',
        kind: 'doctor',
        // Deliberately no --force: destructive repairs roll the install back
        // or delete installed files, and a button labelled "repair" must not
        // do that without the user asking for it explicitly.
        confirmBody: t('This writes the safe automated repairs into your game install.'),
        run: () => doctor({ fix: true }),
      },
      {
        id: 'apply',
        label: t('Apply mods'),
        description: t('Write the current profile into the game install without launching.'),
        icon: <Wrench className="h-4 w-4" aria-hidden="true" />,
        tone: 'primary',
        kind: 'run',
        confirmBody: t('This writes the current profile into your game install.'),
        run: () => applyMods(),
      },
      {
        id: 'restore',
        label: t('Restore originals'),
        description: t('Put every modified file back to its stock state.'),
        icon: <RotateCcw className="h-4 w-4" aria-hidden="true" />,
        tone: 'danger',
        kind: 'run',
        confirmBody: t(
          'This puts every modified file back to its stock state, undoing the applied mods and removing the loader.',
        ),
        run: () => restoreAll(),
      },
      {
        id: 'build',
        label: t('Build'),
        description: t('Generate assets and apply the current mod set in one pass.'),
        icon: <ServerCrash className="h-4 w-4" aria-hidden="true" />,
        tone: 'gilt',
        kind: 'run',
        confirmBody: t(
          'This generates assets and writes the current mod set into your game install.',
        ),
        run: () => build(),
      },
      {
        id: 'run-vanilla',
        label: t('Run vanilla'),
        description: t('Restore first, then hand off to Ravenswatch through Steam.'),
        icon: <Play className="h-4 w-4" aria-hidden="true" />,
        tone: 'default',
        kind: 'run',
        run: () => launch('vanilla'),
      },
      {
        id: 'run-modded',
        label: t('Run modded'),
        description: t('Apply mods, launch the game, and auto-restore after exit.'),
        icon: <CheckCircle2 className="h-4 w-4" aria-hidden="true" />,
        tone: 'primary',
        kind: 'run',
        run: () => launch('modded'),
      },
    ],
    [launch, t],
  );

  const runCommand = async (spec: CommandSpec) => {
    if (busyId) return;
    if (spec.confirmBody) {
      const ok = await dialog.confirm({
        title: t('Run {command}?', { command: spec.label }),
        body: spec.confirmBody,
        confirmLabel: t('Run'),
        destructive: spec.tone === 'danger',
      });
      if (!ok) return;
    }
    const startedAt = Date.now();
    // Entry id is the identity used to patch the row when the command
    // finishes — matching on label + timestamp updated every row of a
    // command run twice in the same millisecond.
    const entryId = `${spec.id}-${startedAt}`;
    setBusyId(spec.id);
    setEntries((current) => [
      { id: entryId, label: spec.label, kind: spec.kind, status: 'running', startedAt },
      ...current,
    ]);

    const patch = (fields: Partial<CommandEntry>) =>
      setEntries((current) =>
        current.map((entry) => (entry.id === entryId ? { ...entry, ...fields } : entry)),
      );

    try {
      const result = await spec.run();
      // A RunResult with ok:false is a failed command, not a failed call —
      // the sidecar answered, it just answered "no".
      const failed = isRecord(result) && result.ok === false;
      patch({
        status: failed ? 'error' : 'success',
        finishedAt: Date.now(),
        result,
      });
      toast.push(
        failed
          ? t('{command} failed — see the log below.', { command: spec.label })
          : t('{command} finished.', { command: spec.label }),
        failed ? 'error' : 'success',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      patch({ status: 'error', finishedAt: Date.now(), error: message });
      // `explainError` returns an English source; translate it here.
      toast.push(
        t('{command} failed: {reason}', {
          command: spec.label,
          reason: t(explainError(message).title),
        }),
        'error',
      );
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t('Commands')}
        subtitle={t('Run the common rsmm lifecycle commands from one place.')}
      />

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">{t('Quick actions')}</h3>
        <Fleuron className="my-3" />
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {commands.map((command) => (
            <Panel key={command.id} variant="inset" className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-serif text-base text-parchment">{command.label}</p>
                  <p className="mt-1 text-sm text-ash">{command.description}</p>
                </div>
                <MonoTag
                  tone={
                    command.tone === 'primary' || command.tone === 'danger'
                      ? 'crimson'
                      : command.tone
                  }
                >
                  {command.id}
                </MonoTag>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={command.tone === 'default' ? 'default' : command.tone}
                  onClick={() => runCommand(command)}
                  disabled={busyId !== null || (launchBusy && !command.readOnly)}
                  title={
                    launchBusy && !command.readOnly
                      ? t('Unavailable while Ravenswatch is launching or running')
                      : undefined
                  }
                >
                  {command.icon}
                  <span>{busyId === command.id ? t('Running…') : t('Run')}</span>
                </Button>
              </div>
            </Panel>
          ))}
        </div>
      </Panel>

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h3 className="font-fraktur text-xl text-parchment">{t('Command log')}</h3>
            <p className="font-serif-italic mt-1 text-ash">
              {t('Outputs from the last commands you ran in this page.')}
            </p>
          </div>
          <Button type="button" size="sm" onClick={() => setEntries([])}>
            {t('Clear log')}
          </Button>
        </div>
        <Fleuron className="my-3" />
        <div className="space-y-3">
          {entries.length === 0 ? (
            <p className="font-serif-italic text-ash">{t('No commands have been run yet.')}</p>
          ) : (
            entries.map((entry) => (
              <div key={entry.id} className="border border-border bg-pitch/60 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <p className="font-serif-italic text-parchment">{entry.label}</p>
                    <MonoTag
                      tone={
                        entry.status === 'success'
                          ? 'gilt'
                          : entry.status === 'error'
                            ? 'crimson'
                            : 'default'
                      }
                    >
                      {entry.status === 'running'
                        ? t('running')
                        : entry.status === 'success'
                          ? t('success')
                          : entry.status === 'error'
                            ? t('error')
                            : t('idle')}
                    </MonoTag>
                  </div>
                  <span className="font-mono text-xs text-ash">
                    {formatClock(entry.startedAt, t.tag)}
                    {formatDuration(entry.startedAt, entry.finishedAt)
                      ? ` · ${formatDuration(entry.startedAt, entry.finishedAt)}`
                      : ''}
                  </span>
                </div>
                {entry.status === 'running' ? (
                  <p className="font-serif-italic mt-3 flex items-center gap-2 text-ash">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    {t('Working…')}
                  </p>
                ) : (
                  <CommandResult kind={entry.kind} result={entry.result} error={entry.error} />
                )}
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}
