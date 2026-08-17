import { createFileRoute } from '@tanstack/react-router';
import { invoke } from '@tauri-apps/api/core';
import { ChevronDown, EyeOff, ShieldAlert, Trash2 } from 'lucide-react';
import { type KeyboardEvent, useEffect, useMemo, useState } from 'react';
import { Fleuron, Panel, SectionHeader } from '../components/chrome';
import { useLaunch } from '../components/launch';
import { useToast } from '../components/toast';
import { UpdaterSettings } from '../components/updater';
import {
  DEFAULT_FONT,
  DEFAULT_FONT_SCALE,
  type Density,
  FONT_CHOICES,
  FONT_PRESETS,
  MAX_FONT_SCALE,
  MIN_FONT_SCALE,
  normalizeFont,
  normalizeFontScale,
} from '../lib/appearance';
import {
  type LauncherLogEntry,
  clearLauncherLog,
  parseLauncherLog,
  readLauncherLog,
} from '../lib/launcher-log';
import { type LoaderFlag, getLoaderFlags, setLoaderFlags } from '../lib/rsmm';
import { useApp } from '../store';

export const Route = createFileRoute('/settings')({
  component: SettingsPage,
});

/** Poll cadence for the launcher log while a launch is live. */
const LOG_POLL_INTERVAL_MS = 3000;

const DENSITY_CHOICES: { value: Density; hint: string }[] = [
  { value: 'cozy', hint: 'Roomy padding — the default.' },
  { value: 'compact', hint: 'Tighter panels; more fits on screen.' },
];

/**
 * Settings is grouped, not split.
 *
 * Every panel still lives on this one route — nothing moved to another tab of
 * the app — but eight stacked panels had turned the page into a long scroll
 * where the thing you came for was never on screen. The groups below are the
 * whole page, one group at a time.
 *
 * A hidden group is UNMOUNTED, not hidden with CSS: the launcher log polls
 * every few seconds during a launch and the loader/GPU panels each hit the
 * sidecar on mount, and none of that should run while you are reading a
 * different group.
 */
const TABS = [
  { id: 'general', label: 'General', hint: 'Paths, mod sources, updates' },
  { id: 'appearance', label: 'Appearance', hint: 'Typeface, density, content' },
  { id: 'game', label: 'Game', hint: 'Loader features, graphics' },
  { id: 'diagnostics', label: 'Diagnostics', hint: 'Launcher log, crash reports' },
] as const;

type SettingsTab = (typeof TABS)[number]['id'];

function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>('general');

  return (
    <div className="space-y-6">
      <SectionHeader title="Settings" subtitle="Where things live. How they look." />

      <SettingsTabs value={tab} onChange={setTab} />

      <div
        role="tabpanel"
        id={`settings-panel-${tab}`}
        aria-labelledby={`settings-tab-${tab}`}
        className="space-y-6"
      >
        {tab === 'general' ? (
          <>
            <PathsPanel />
            <SourcesPanel />
            <UpdatesPanel />
          </>
        ) : null}
        {tab === 'appearance' ? <AppearancePanel /> : null}
        {tab === 'game' ? (
          <>
            <LoaderFlagsPanel />
            <GraphicsPanel />
          </>
        ) : null}
        {tab === 'diagnostics' ? (
          <>
            <LauncherLogPanel />
            <PrivacyPanel />
          </>
        ) : null}
      </div>
    </div>
  );
}

function SettingsTabs({
  value,
  onChange,
}: {
  value: SettingsTab;
  onChange: (tab: SettingsTab) => void;
}) {
  // Arrow keys move between tabs, and only the selected tab is a tab stop —
  // the standard tablist contract, so Tab from the tab strip lands in the
  // panel rather than walking four buttons first.
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const delta = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const i = TABS.findIndex((t) => t.id === value);
    const next = TABS[(i + delta + TABS.length) % TABS.length]?.id;
    if (!next) return;
    onChange(next);
    document.getElementById(`settings-tab-${next}`)?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label="Settings sections"
      className="flex flex-wrap gap-1 border-b border-border"
      onKeyDown={onKeyDown}
    >
      {TABS.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`settings-tab-${t.id}`}
            aria-selected={active}
            aria-controls={`settings-panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            title={t.hint}
            onClick={() => onChange(t.id)}
            className={`font-mono -mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
              active
                ? 'border-crimson text-parchment'
                : 'border-transparent text-ash hover:text-parchment'
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

function PathsPanel() {
  const settings = useApp((s) => s.settings);
  const update = useApp((s) => s.updateSettings);

  return (
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
  );
}

function SourcesPanel() {
  const settings = useApp((s) => s.settings);
  const update = useApp((s) => s.updateSettings);
  const [newSource, setNewSource] = useState('');
  const [sourceError, setSourceError] = useState<string | null>(null);
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

  return (
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
  );
}

function UpdatesPanel() {
  return (
    <Panel>
      <h3 className="font-fraktur text-xl text-parchment">Updates</h3>
      <Fleuron className="my-3" />
      <p className="font-serif-italic text-ash mb-3">
        RSMM checks for new releases automatically. You can also check manually.
      </p>
      <UpdaterSettings />
    </Panel>
  );
}

/** The launcher log, filtered. Mounted only while its group is open, which is
 * also what stops the live poll below when you are elsewhere in Settings. */
function LauncherLogPanel() {
  const [launcherLog, setLauncherLog] = useState('');
  const [logQuery, setLogQuery] = useState('');
  const [logLevel, setLogLevel] = useState<'all' | 'info' | 'warn' | 'error'>('all');
  const [loadingLog, setLoadingLog] = useState(false);
  const toast = useToast();
  const { busy: launchBusy } = useLaunch();

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

  // While a launch is in flight the log is the only place a stuck apply or a
  // failed restore shows up, and it is written by another process — poll it
  // so the user isn't left hitting Refresh to find out what happened.
  useEffect(() => {
    if (!launchBusy) return;
    let cancelled = false;
    const handle = window.setInterval(() => {
      readLauncherLog().then(
        (log) => {
          if (!cancelled) setLauncherLog(log);
        },
        () => undefined,
      );
    }, LOG_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [launchBusy]);

  const onClearLog = async () => {
    await clearLauncherLog();
    setLauncherLog('');
    toast.push('Launcher log cleared.', 'success');
  };

  const logEntries = useMemo(() => parseLauncherLog(launcherLog), [launcherLog]);
  const query = logQuery.trim().toLowerCase();
  const filteredEntries = logEntries.filter((entry) => {
    if (logLevel !== 'all' && entry.level !== logLevel) return false;
    if (!query) return true;
    return entry.raw.toLowerCase().includes(query);
  });

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-fraktur text-xl text-parchment">Launcher Log</h3>
          <p className="font-serif-italic text-ash mt-1">
            Current run only. Cleared whenever you launch Vanilla or Modded.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {launchBusy ? (
            <span className="font-mono inline-flex items-center gap-1.5 border border-gilt/60 px-2 py-1 text-[10px] text-gilt">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-gilt" aria-hidden />
              live
            </span>
          ) : null}
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
          <ChevronDown
            className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ash"
            aria-hidden="true"
          />
        </div>
      </div>
      {filteredEntries.length === 0 ? (
        <p className="font-serif-italic border border-border bg-pitch/60 p-3 text-ash">
          {logEntries.length > 0
            ? 'No launcher log entries match the current filters.'
            : 'No launcher log entries yet. Launch the game once and they will show up here.'}
        </p>
      ) : (
        <ul className="max-h-72 divide-y divide-border/60 overflow-auto border border-border bg-pitch/60">
          {filteredEntries.map((entry, i) => (
            // Log lines carry no id and repeat verbatim, so position is
            // part of the identity.
            <LogRow key={`${i}-${entry.raw}`} entry={entry} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function AppearancePanel() {
  const settings = useApp((s) => s.settings);
  const update = useApp((s) => s.updateSettings);

  return (
    <Panel>
      <h3 className="font-fraktur text-xl text-parchment">Appearance</h3>
      <Fleuron className="my-3" />
      <TypographyControls />
      <Fleuron className="my-3" />
      <fieldset className="flex flex-col gap-2">
        <legend className="font-mono mb-2 text-ash">Density</legend>
        {DENSITY_CHOICES.map(({ value, hint }) => (
          <label key={value} className="flex cursor-pointer items-start gap-2 text-parchment">
            <input
              type="radio"
              name="density"
              checked={settings.density === value}
              onChange={() => update({ density: value })}
              className="mt-1 accent-crimson"
            />
            <span>
              <span className="font-serif-italic block capitalize">{value}</span>
              <span className="font-serif-italic block text-sm text-ash">{hint}</span>
            </span>
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
  );
}

function PrivacyPanel() {
  const settings = useApp((s) => s.settings);
  const update = useApp((s) => s.updateSettings);

  return (
    <Panel>
      <h3 className="font-fraktur text-xl text-parchment">Privacy</h3>
      <Fleuron className="my-3" />
      <label className="flex cursor-pointer items-start gap-3 text-parchment">
        <input
          type="checkbox"
          checked={settings.crashReports}
          onChange={(e) => update({ crashReports: e.target.checked })}
          className="mt-1 h-4 w-4 accent-crimson"
        />
        <span>
          <span className="font-mono text-sm flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-crimson" />
            Send crash reports
          </span>
          <span className="font-serif-italic mt-1 block text-sm text-ash">
            When the app hits an unexpected error, send the error type, message, stack trace, RSMM
            version and OS to the RSMM API so it can be fixed. No mod list, no file paths, no
            account details. Turning this off keeps crashes in your local launcher log only.
          </span>
        </span>
      </label>
    </Panel>
  );
}

const LOG_LEVEL_TONE: Record<LauncherLogEntry['level'], string> = {
  info: 'border-border text-smoke',
  warn: 'border-gilt/60 text-gilt',
  error: 'border-crimson/70 bg-crimson/15 text-parchment',
  other: 'border-border text-smoke',
};

/** One launcher-log line: local time, level chip, message, and the JSON
 * context tucked behind a disclosure so a busy line stays one row tall. */
function LogRow({ entry }: { entry: LauncherLogEntry }) {
  return (
    <li className="px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-mono shrink-0 text-xs text-ash">
          {entry.at ? new Date(entry.at).toLocaleTimeString() : '—'}
        </span>
        <span
          className={`font-mono shrink-0 border px-1.5 py-[1px] text-[10px] ${LOG_LEVEL_TONE[entry.level]}`}
        >
          {entry.level}
        </span>
        <span className="min-w-0 break-words text-sm text-parchment/90">{entry.message}</span>
      </div>
      {entry.context ? (
        <details className="mt-1">
          <summary className="font-mono cursor-pointer text-[10px] text-ash hover:text-parchment">
            context
          </summary>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-xs text-ash">
            {entry.context}
          </pre>
        </details>
      ) : null}
    </li>
  );
}

/** Typeface + UI scale. Both are written straight to CSS vars on <html> by
 * `applyAppearance` (subscribed in main.tsx), so every change previews live
 * across the whole app — this panel only edits the stored values. */
function TypographyControls() {
  const settings = useApp((s) => s.settings);
  const update = useApp((s) => s.updateSettings);
  const font = normalizeFont(settings.fontFamily);
  const scale = normalizeFontScale(settings.fontScale);
  const isDefault = font === DEFAULT_FONT && scale === DEFAULT_FONT_SCALE;

  return (
    <div className="space-y-4">
      <fieldset className="flex flex-col gap-2">
        <legend className="font-mono mb-2 text-ash">Font</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {FONT_CHOICES.map((choice) => {
            const preset = FONT_PRESETS[choice];
            const active = font === choice;
            return (
              <label
                key={choice}
                className={`flex cursor-pointer items-start gap-2 border px-3 py-2 ${
                  active ? 'border-gilt/60 bg-gilt/10' : 'border-border hover:border-gilt/30'
                }`}
              >
                <input
                  type="radio"
                  name="font-family"
                  checked={active}
                  onChange={() => update({ fontFamily: choice })}
                  className="mt-1 accent-crimson"
                />
                <span className="min-w-0">
                  <span className="block text-parchment" style={{ fontFamily: preset.vars.body }}>
                    {preset.label}
                  </span>
                  <span className="font-serif-italic block text-sm text-ash">{preset.hint}</span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div>
        <div className="mb-2 flex items-center justify-between gap-3">
          <span className="font-mono text-ash">Font size</span>
          <span className="font-mono text-parchment">{scale}%</span>
        </div>
        <input
          type="range"
          min={MIN_FONT_SCALE}
          max={MAX_FONT_SCALE}
          step={5}
          value={scale}
          aria-label="UI font size"
          onChange={(e) => update({ fontScale: normalizeFontScale(e.target.value) })}
          className="w-full accent-crimson"
        />
        <div className="font-mono mt-1 flex justify-between text-[10px] text-ash">
          <span>{MIN_FONT_SCALE}%</span>
          <span>100%</span>
          <span>{MAX_FONT_SCALE}%</span>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border border-border px-3 py-2">
        <p className="font-serif-italic min-w-0 text-ash">
          The quick brown fox jumps over the lazy dog — 0123456789
        </p>
        <button
          type="button"
          disabled={isDefault}
          onClick={() => update({ fontFamily: DEFAULT_FONT, fontScale: DEFAULT_FONT_SCALE })}
          className="shrink-0 border border-border px-3 py-1.5 text-sm text-ash hover:border-gilt/50 hover:text-parchment disabled:opacity-40 disabled:hover:border-border disabled:hover:text-ash"
        >
          Reset
        </button>
      </div>
    </div>
  );
}

/**
 * Software-rendering escape hatch.
 *
 * A machine blue-screened with VIDEO_SCHEDULER_INTERNAL_ERROR (bug check
 * 0x119) with a mod page open: a display-driver fault raised by the Windows
 * video scheduler. The app cannot cause that on its own — it can only submit
 * GPU work a broken driver mishandles — but "update your driver" is a poor
 * only-answer, so this turns the app's GPU usage off entirely.
 *
 * The renderer is chosen when the webview process starts, so the change lands
 * on the next launch. Saying that plainly beats a toggle that appears to do
 * nothing.
 */
function GraphicsPanel() {
  const [disabled, setDisabled] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const [restartNeeded, setRestartNeeded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    invoke<boolean>('gpu_acceleration_disabled')
      .then((v) => {
        if (alive) setDisabled(v);
      })
      .catch(() => {
        if (alive) setDisabled(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const toggle = async () => {
    if (disabled === null || pending) return;
    setPending(true);
    setError(null);
    try {
      const next = await invoke<boolean>('set_gpu_acceleration_disabled', { disabled: !disabled });
      setDisabled(next);
      setRestartNeeded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  };

  return (
    <Panel>
      <h3 className="font-fraktur text-xl text-parchment">Graphics</h3>
      <Fleuron className="my-3" />
      <p className="font-serif-italic text-ash mb-3">
        RSMM draws through your GPU like any browser window. If your machine crashes, freezes or
        blue-screens while RSMM is open — especially with a display-driver bug check such as{' '}
        <span className="font-mono">VIDEO_SCHEDULER_INTERNAL_ERROR</span> — switch this on to render
        in software instead. Update your GPU driver as well; that is the real fix.
      </p>
      <label className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={disabled === true}
          disabled={disabled === null || pending}
          onChange={() => void toggle()}
          className="h-4 w-4 accent-crimson"
        />
        <span className="text-parchment">Disable GPU acceleration (software rendering)</span>
      </label>
      {restartNeeded ? (
        <p className="font-mono mt-3 text-sm text-gilt">Restart RSMM for this to take effect.</p>
      ) : null}
      {error ? (
        <p className="font-mono mt-3 text-sm text-crimson" role="alert">
          {error}
        </p>
      ) : null}
    </Panel>
  );
}

/** Loader feature flags. The native loader reads these from a JSON file next
 * to winhttp.dll (so they work on native Windows too, where Steam launch
 * options cannot set environment variables). Only flags the bridge marks
 * `safe` are togglable here; locked ones are shown greyed-out with the reason. */
function LoaderFlagsPanel() {
  const [available, setAvailable] = useState<LoaderFlag[]>([]);
  const [enabled, setEnabled] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loaderInstalled, setLoaderInstalled] = useState<boolean | null>(null);
  const [launchOptionsPresent, setLaunchOptionsPresent] = useState<boolean | null | undefined>(
    undefined,
  );
  const toast = useToast();

  useEffect(() => {
    let cancelled = false;
    getLoaderFlags().then(
      (res) => {
        if (cancelled) return;
        if (!res) {
          setUnavailable(true);
        } else {
          setAvailable(res.available ?? []);
          setEnabled(new Set(res.enabled ?? []));
          setUnavailable(!res.gameDir);
          setLoaderInstalled(res.loaderInstalled ?? null);
          setLaunchOptionsPresent(res.launchOptionsPresent);
        }
        setLoading(false);
      },
      () => {
        if (cancelled) return;
        setUnavailable(true);
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = async (flag: LoaderFlag, on: boolean) => {
    if (!flag.safe) return;
    const next = new Set(enabled);
    if (on) next.add(flag.name);
    else next.delete(flag.name);
    setEnabled(next); // optimistic
    setSaving(flag.name);
    try {
      const res = await setLoaderFlags([...next]);
      if (res?.ok) {
        setEnabled(new Set(res.enabled ?? []));
      } else {
        setEnabled(enabled); // revert
        toast.push(res?.error ?? 'Could not save loader flags.', 'error');
      }
    } catch {
      setEnabled(enabled); // revert
      toast.push('Could not save loader flags.', 'error');
    } finally {
      setSaving(null);
    }
  };

  return (
    <Panel>
      <h3 className="font-fraktur text-xl text-parchment">Loader features</h3>
      <Fleuron className="my-3" />
      <p className="font-serif-italic text-ash mb-3">
        Opt-in hooks the script loader installs at launch. Off by default — most mods don't need
        them. Changes take effect next time you launch Modded.
      </p>
      {!loading && !unavailable ? (
        <div className="mb-4 flex flex-wrap gap-2">
          <StatusChip
            label="Loader DLL"
            state={loaderInstalled === null ? 'unknown' : loaderInstalled ? 'ok' : 'missing'}
            okText="installed"
            missingText="not installed — launch Modded once"
          />
          {launchOptionsPresent !== null && launchOptionsPresent !== undefined ? (
            <StatusChip
              label="Launch options"
              state={launchOptionsPresent ? 'ok' : 'missing'}
              okText="winhttp override set"
              missingText="missing — launch Modded to set"
            />
          ) : null}
        </div>
      ) : null}
      {loading ? (
        <p className="font-mono text-sm text-ash">Loading…</p>
      ) : unavailable ? (
        <p className="font-mono text-sm text-ash">
          Set your game install path under General, then reopen Settings to manage loader features.
        </p>
      ) : (
        <ul className="space-y-3">
          {available.map((flag) => {
            const on = enabled.has(flag.name);
            return (
              <li
                key={flag.name}
                className="flex items-start justify-between gap-4 border border-border px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-parchment">{flag.label}</span>
                    {!flag.safe ? (
                      <span className="font-mono rounded border border-crimson/60 px-1.5 py-0.5 text-[10px] uppercase text-crimson">
                        locked
                      </span>
                    ) : null}
                  </div>
                  <p className="font-serif-italic mt-0.5 text-sm text-ash">{flag.description}</p>
                </div>
                <label className="flex shrink-0 cursor-pointer items-center gap-2 pt-0.5">
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={!flag.safe || saving === flag.name}
                    onChange={(e) => toggle(flag, e.target.checked).catch(() => undefined)}
                    className="h-4 w-4 accent-crimson disabled:opacity-40"
                  />
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

function StatusChip({
  label,
  state,
  okText,
  missingText,
}: {
  label: string;
  state: 'ok' | 'missing' | 'unknown';
  okText: string;
  missingText: string;
}) {
  const tone =
    state === 'ok'
      ? 'border-gilt/50 text-gilt'
      : state === 'missing'
        ? 'border-crimson/60 text-crimson'
        : 'border-border text-ash';
  const detail = state === 'ok' ? okText : state === 'missing' ? missingText : 'unknown';
  return (
    <span className={`font-mono inline-flex items-center gap-1.5 border px-2 py-1 text-xs ${tone}`}>
      <span className="text-parchment">{label}:</span>
      <span>{detail}</span>
    </span>
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
