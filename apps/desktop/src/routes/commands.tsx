import { createFileRoute } from '@tanstack/react-router';
import {
  CheckCircle2,
  Play,
  RotateCcw,
  ServerCrash,
  ShieldCheck,
  Terminal,
  Wrench,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import {
  applyMods,
  build,
  doctor,
  listLocalMods,
  restoreAll,
  runModded,
  runVanilla,
} from '../lib/rsmm';

type CommandStatus = 'idle' | 'running' | 'success' | 'error';

interface CommandEntry {
  id: string;
  label: string;
  status: CommandStatus;
  startedAt: string;
  finishedAt?: string;
  output: string;
}

interface CommandSpec {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  tone: 'default' | 'primary' | 'gilt' | 'danger';
  run: () => Promise<unknown>;
}

export const Route = createFileRoute('/commands')({
  component: CommandsPage,
});

function stringifyResult(value: unknown): string {
  if (value == null) return 'No output.';
  if (typeof value === 'string') return value || 'No output.';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function CommandsPage() {
  const [entries, setEntries] = useState<CommandEntry[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const commands = useMemo<CommandSpec[]>(
    () => [
      {
        id: 'list',
        label: 'List local mods',
        description: 'Show every mod currently installed in the local mods folder.',
        icon: <Terminal className="h-4 w-4" aria-hidden="true" />,
        tone: 'default',
        run: () => listLocalMods(),
      },
      {
        id: 'doctor',
        label: 'Doctor',
        description: 'Run the health check for paths, loader, and core setup.',
        icon: <ShieldCheck className="h-4 w-4" aria-hidden="true" />,
        tone: 'gilt',
        run: () => doctor(),
      },
      {
        id: 'apply',
        label: 'Apply mods',
        description: 'Write the current profile into the game install without launching.',
        icon: <Wrench className="h-4 w-4" aria-hidden="true" />,
        tone: 'primary',
        run: () => applyMods(),
      },
      {
        id: 'restore',
        label: 'Restore originals',
        description: 'Put every modified file back to its stock state.',
        icon: <RotateCcw className="h-4 w-4" aria-hidden="true" />,
        tone: 'danger',
        run: () => restoreAll(),
      },
      {
        id: 'build',
        label: 'Build',
        description: 'Generate assets and apply the current mod set in one pass.',
        icon: <ServerCrash className="h-4 w-4" aria-hidden="true" />,
        tone: 'gilt',
        run: () => build(),
      },
      {
        id: 'run-vanilla',
        label: 'Run vanilla',
        description: 'Restore first, then hand off to Ravenswatch through Steam.',
        icon: <Play className="h-4 w-4" aria-hidden="true" />,
        tone: 'default',
        run: () => runVanilla(),
      },
      {
        id: 'run-modded',
        label: 'Run modded',
        description: 'Apply mods, launch the game, and auto-restore after exit.',
        icon: <CheckCircle2 className="h-4 w-4" aria-hidden="true" />,
        tone: 'primary',
        run: () => runModded(),
      },
    ],
    [],
  );

  const runCommand = async (spec: CommandSpec) => {
    if (busyId) return;
    const startedAt = new Date().toISOString();
    setBusyId(spec.id);
    setEntries((current) => [
      {
        id: `${spec.id}-${Date.now()}`,
        label: spec.label,
        status: 'running',
        startedAt,
        output: 'Running…',
      },
      ...current,
    ]);

    try {
      const result = await spec.run();
      const output = stringifyResult(result);
      const finishedAt = new Date().toISOString();
      setEntries((current) =>
        current.map((entry) =>
          entry.label === spec.label && entry.startedAt === startedAt
            ? { ...entry, status: 'success', finishedAt, output }
            : entry,
        ),
      );
    } catch (error) {
      const finishedAt = new Date().toISOString();
      const output = error instanceof Error ? error.message : String(error);
      setEntries((current) =>
        current.map((entry) =>
          entry.label === spec.label && entry.startedAt === startedAt
            ? { ...entry, status: 'error', finishedAt, output }
            : entry,
        ),
      );
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Commands"
        subtitle="Run the common rsmm lifecycle commands from one place."
      />

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">Quick actions</h3>
        <Fleuron className="my-3" />
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {commands.map((command) => (
            <div key={command.id} className="border border-border/70 bg-pitch/40 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-serif-italic text-base text-parchment">{command.label}</p>
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
                  disabled={busyId !== null}
                >
                  {command.icon}
                  <span>{busyId === command.id ? 'Running…' : 'Run'}</span>
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="font-fraktur text-xl text-parchment">Command log</h3>
            <p className="font-serif-italic mt-1 text-ash">
              Outputs from the last commands you ran in this page.
            </p>
          </div>
          <Button type="button" size="sm" onClick={() => setEntries([])}>
            Clear log
          </Button>
        </div>
        <Fleuron className="my-3" />
        <div className="space-y-3">
          {entries.length === 0 ? (
            <p className="font-serif-italic text-ash">No commands have been run yet.</p>
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
                      {entry.status}
                    </MonoTag>
                  </div>
                  <span className="font-mono text-xs text-ash">{entry.startedAt}</span>
                </div>
                <pre className="mt-3 overflow-auto whitespace-pre-wrap font-mono text-sm text-parchment/90">
                  {entry.output}
                </pre>
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}
