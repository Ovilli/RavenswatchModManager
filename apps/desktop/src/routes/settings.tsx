import { createFileRoute } from '@tanstack/react-router';
import { ChevronDown, EyeOff, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Fleuron, Panel, SectionHeader } from '../components/chrome';
import { useToast } from '../components/toast';
import { UpdaterSettings } from '../components/updater';
import { clearLauncherLog, readLauncherLog } from '../lib/launcher-log';
import { useApp } from '../store';

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
});

function SettingsPage() {
  const settings = useApp((s) => s.settings);
  const update = useApp((s) => s.updateSettings);
  const [newSource, setNewSource] = useState('');
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [launcherLog, setLauncherLog] = useState('');
  const [logQuery, setLogQuery] = useState('');
  const [logLevel, setLogLevel] = useState<'all' | 'info' | 'warn' | 'error'>('all');
  const [loadingLog, setLoadingLog] = useState(false);
  const toast = useToast();

  const addSource = () => {
    const v = newSource.trim();
    if (!v) {
      setSourceError('Enter a URL first.');
      return;
    }
    let parsed: URL;
    try {
      parsed = new URL(v);
    } catch {
      setSourceError('Not a valid URL (include https:// or http://).');
      return;
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      setSourceError('URL must use http or https.');
      return;
    }
    if (settings.sources.includes(v)) {
      setSourceError('That source is already in the list.');
      return;
    }
    update({ sources: [...settings.sources, v] });
    setNewSource('');
    setSourceError(null);
    toast.push('Mod source added.', 'success');
  };

  const refreshLog = async () => {
    setLoadingLog(true);
    try {
      setLauncherLog(await readLauncherLog());
    } finally {
      setLoadingLog(false);
    }
  };

  useEffect(() => {
    setLoadingLog(true);
    readLauncherLog().then(
      (log) => {
        setLauncherLog(log);
        setLoadingLog(false);
      },
      () => {
        setLoadingLog(false);
      },
    );
  }, []);

  const onClearLog = async () => {
    await clearLauncherLog();
    setLauncherLog('');
    toast.push('Launcher log cleared.', 'success');
  };

  const filteredLauncherLog = launcherLog
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim();
      if (!trimmed) return false;
      if (logLevel !== 'all' && !trimmed.includes(`[${logLevel.toUpperCase()}]`)) {
        return false;
      }
      if (!logQuery.trim()) return true;
      return trimmed.toLowerCase().includes(logQuery.trim().toLowerCase());
    })
    .join('\n');

  return (
    <div className="space-y-6">
      <SectionHeader title="Settings" subtitle="Where things live. How they look." />

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">Paths</h3>
        <Fleuron className="my-3" />
        <Field
          label="Game install"
          value={settings.gameDir}
          onChange={(v) => update({ gameDir: v })}
          validate={(v) => validateDirPath(v, 'Game install path')}
        />
        <Field
          label="Backup folder"
          value={settings.backupDir}
          onChange={(v) => update({ backupDir: v })}
          validate={(v) => validateDirPath(v, 'Backup folder path')}
        />
        <Field
          label="Mods folder"
          value={settings.modsDir}
          placeholder="Leave empty to use the default rsmm mods folder"
          onChange={(v) => update({ modsDir: v })}
          validate={(v) => validateDirPath(v, 'Mods folder path')}
        />
      </Panel>

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">Mod sources</h3>
        <Fleuron className="my-3" />
        <ul className="space-y-2">
          {settings.sources.map((src) => (
            <li
              key={src}
              className="flex items-center justify-between gap-3 border border-border px-3 py-2"
            >
              <span className="font-mono text-parchment break-all">{src}</span>
              <button
                type="button"
                onClick={() => update({ sources: settings.sources.filter((s) => s !== src) })}
                className="font-mono text-ash hover:text-crimson"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex items-center gap-2">
          <input
            value={newSource}
            onChange={(e) => {
              setNewSource(e.target.value);
              if (sourceError) setSourceError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addSource();
              }
            }}
            placeholder="https://example.invalid/registry"
            className="font-mono flex-1 border border-border bg-pitch/60 px-3 py-2 text-parchment placeholder:text-ash focus:border-gilt/60 focus:outline-none"
            aria-invalid={sourceError ? true : undefined}
          />
          <button
            type="button"
            onClick={addSource}
            className="border border-crimson bg-crimson/80 px-3 py-2 text-parchment hover:bg-oxblood"
          >
            Add
          </button>
        </div>
        {sourceError ? (
          <p className="font-mono mt-2 text-sm text-crimson" role="alert">
            {sourceError}
          </p>
        ) : null}
      </Panel>

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">Updates</h3>
        <Fleuron className="my-3" />
        <p className="font-serif-italic text-ash mb-3">
          RSMM checks for new releases automatically. You can also check manually.
        </p>
        <UpdaterSettings />
      </Panel>

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-fraktur text-xl text-parchment">Launcher Log</h3>
            <p className="font-serif-italic text-ash mt-1">
              Current run only. Cleared whenever you launch Vanilla or Modded.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => refreshLog().catch(() => undefined)}
              className="border border-border px-3 py-2 text-sm text-ash hover:border-gilt/50 hover:text-parchment"
            >
              {loadingLog ? 'Refreshing…' : 'Refresh'}
            </button>
            <button
              type="button"
              onClick={() => onClearLog().catch(() => undefined)}
              className="border border-crimson bg-crimson/80 px-3 py-2 text-sm text-parchment hover:bg-oxblood"
            >
              Clear
            </button>
          </div>
        </div>
        <Fleuron className="my-3" />
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            value={logQuery}
            onChange={(e) => setLogQuery(e.target.value)}
            placeholder="Search launcher log..."
            className="font-mono min-w-56 flex-1 border border-border bg-pitch/60 px-3 py-2 text-sm text-parchment placeholder:text-ash focus:border-gilt/60 focus:outline-none"
          />
          <div className="relative inline-flex">
            <select
              value={logLevel}
              onChange={(e) => setLogLevel(e.target.value as 'all' | 'info' | 'warn' | 'error')}
              className="select-grim font-mono appearance-none border border-border bg-pitch/60 py-2 pl-3 pr-9 text-sm text-parchment focus:border-gilt/60 focus:outline-none"
            >
              <option value="all">All levels</option>
              <option value="info">Info</option>
              <option value="warn">Warnings</option>
              <option value="error">Errors</option>
            </select>
            <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ash" aria-hidden="true" />
          </div>
        </div>
        <pre className="font-mono max-h-72 overflow-auto whitespace-pre-wrap border border-border bg-pitch/60 p-3 text-sm text-parchment/90">
          {filteredLauncherLog.trim()
            ? filteredLauncherLog
            : launcherLog.trim()
              ? 'No launcher log entries match the current filters.'
              : 'No launcher log entries yet.'}
        </pre>
      </Panel>

      <Panel>
        <h3 className="font-fraktur text-xl text-parchment">Appearance</h3>
        <Fleuron className="my-3" />
        <fieldset className="flex flex-col gap-2">
          <legend className="font-mono mb-2 text-ash">Density</legend>
          {(['cozy', 'compact'] as const).map((d) => (
            <label key={d} className="flex cursor-pointer items-center gap-2 text-parchment">
              <input
                type="radio"
                name="density"
                checked={settings.density === d}
                onChange={() => update({ density: d })}
                className="accent-crimson"
              />
              <span className="font-serif-italic capitalize">{d}</span>
            </label>
          ))}
        </fieldset>
        <Fleuron className="my-3" />
        <label className="flex cursor-pointer items-center gap-3 text-parchment">
          <input
            type="checkbox"
            checked={settings.showNsfw}
            onChange={(e) => update({ showNsfw: e.target.checked })}
            className="h-4 w-4 accent-crimson"
          />
          <span className="font-mono text-sm flex items-center gap-2">
            <EyeOff className="h-4 w-4 text-crimson" />
            Show NSFW content
          </span>
        </label>
      </Panel>
    </div>
  );
}

/** Lightweight syntactic check. A non-empty path that doesn't smell
 * like a URL or shell metacharacter blob is good enough for inline UI
 * feedback; the real existence check happens when the sidecar tries to
 * read from it. */
function validateDirPath(raw: string, label: string): string | null {
  const v = (raw ?? '').trim();
  if (!v) return null;
  for (const ch of v) {
    const code = ch.codePointAt(0);
    if (code !== undefined && code < 0x20) {
      return `${label} contains control characters.`;
    }
  }
  if (v.includes('://')) {
    return `${label} must be a filesystem path, not a URL.`;
  }
  return null;
}

function Field({
  label,
  value = '',
  placeholder,
  onChange,
  validate,
}: {
  label: string;
  value?: string;
  placeholder?: string;
  onChange: (v: string) => void;
  validate?: (v: string) => string | null;
}) {
  const error = validate ? validate(value) : null;
  return (
    <label className="mb-3 block">
      <span className="font-mono mb-1 block text-ash">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="font-mono w-full border border-border bg-pitch/60 px-3 py-2 text-parchment focus:border-gilt/60 focus:outline-none"
        aria-invalid={error ? true : undefined}
      />
      {error ? (
        <span className="font-mono mt-1 block text-sm text-crimson" role="alert">
          {error}
        </span>
      ) : null}
    </label>
  );
}
