import { createFileRoute } from '@tanstack/react-router';
import {
  AlertTriangle,
  ChevronDown,
  FolderOpen,
  Link2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, CopyButton, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { useLaunch } from '../components/launch';
import { ShareLogDialog } from '../components/share-log-dialog';
import { useDialog, useToast } from '../components/toast';
import { explainError } from '../lib/errors';
import { TParts, useT } from '../lib/i18n-react';
import {
  type LoaderLogLine,
  loaderLogProblems,
  loaderLogTags,
  parseLoaderLog,
} from '../lib/loader-log';
import {
  type LogChunk,
  type TailState,
  appendChunk,
  deleteLoaderLogs,
  emptyTail,
  openLoaderLogsDir,
  readLoaderLogChunk,
  sessionSlice,
} from '../lib/loader-log-tail';
import {
  type ArchivedRun,
  type LoaderHealth,
  type LoaderLogResult,
  gameStatus,
  listLoaderRuns,
  loaderHealth,
  readLoaderLog,
  resetModHealth,
} from '../lib/rsmm';

export const Route = createFileRoute('/log')({
  component: LogPage,
});

/**
 * Poll cadence while following.
 *
 * A poll is now a seek and a read of exactly what the game appended (see
 * `lib/loader-log-tail`), not a Python process spawn, so a second is cheap
 * rather than merely tolerable.
 */
const POLL_MS = 1000;
/** Lines held in memory. Rendering is windowed by the browser, so this can be
 *  generous — it bounds memory, not paint cost. */
const LINE_CAP = 2000;

/** Which log the screen is showing. Archived runs are named, not indexed: the
 *  name is an opaque handle the sidecar resolves against its own listing. */
/** `current` is the run in progress (nothing, with no game up); `last` the last
 *  run that ENDED: the newest log with no game up, the rotated one while a game
 *  writes the newest; `run` an archived run, by name. */
type Source = { kind: 'current' } | { kind: 'last' } | { kind: 'run'; name: string };

/** How often the screen asks whether Ravenswatch is up while it shows the newest
 *  log. A process check, not a file read, so far slower than the tail poll. */
const GAME_POLL_MS = 5000;

/** `t` is passed in: this is a plain helper, and the label is copy. */
function sourceLabel(source: Source, t: (message: string) => string): string {
  if (source.kind === 'current') return t('Current run');
  if (source.kind === 'last') return t('Last run');
  return source.name.replace(/\.log$/, '');
}

function LogPage() {
  const t = useT();
  const { running } = useLaunch();
  const toast = useToast();
  const dialog = useDialog();
  const [source, setSource] = useState<Source>({ kind: 'current' });
  const [runs, setRuns] = useState<ArchivedRun[]>([]);
  const [runsDir, setRunsDir] = useState<string | null>(null);
  const [meta, setMeta] = useState<LoaderLogResult | null>(null);
  const [tail, setTail] = useState<TailState>(emptyTail);
  const [health, setHealth] = useState<LoaderHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [follow, setFollow] = useState(true);
  const [allSessions, setAllSessions] = useState(false);
  const [query, setQuery] = useState('');
  const [tag, setTag] = useState('all');
  const [problemsOnly, setProblemsOnly] = useState(false);
  // Snapshot rather than a live reference: the follow poll replaces the buffer
  // every second, which would rewrite the share preview (and the bytes about
  // to be uploaded) while the user is reading it.
  const [sharing, setSharing] = useState<{ lines: string[]; path: string | null } | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);
  // Read inside the interval without making it a dependency — re-creating the
  // timer on every appended line would reset the cadence continuously.
  const tailRef = useRef(tail);
  tailRef.current = tail;

  // Only the live log grows. Following a finished run would poll a file that
  // will never change again.
  const followable = source.kind === 'current';

  // Whether the game is up, however it was started: `running` only knows about
  // launches from this app, so a game started from Steam would read as stopped,
  // and with no game at all the newest log is the LAST run, not a current one.
  const [processUp, setProcessUp] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const st = await gameStatus();
        if (!cancelled) setProcessUp(st ? !!st.running : null);
      } catch {
        if (!cancelled) setProcessUp(null);
      }
    };
    void check();
    const id = window.setInterval(() => void check(), GAME_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);
  // Unknown (an older sidecar, a failed check) falls back to the launch state.
  const gameUp = !!running || processUp === true;
  // With no game up, "Current run" has nothing to show: the newest log is a
  // finished run, which is "Last run" (user report: the screen kept showing it).
  const idle = followable && !gameUp;
  // While a game writes the newest log, the last FINISHED run is the rotated one.
  const readPrev = source.kind === 'last' && gameUp;

  /** Full reload through the sidecar: it owns game-directory resolution and
   *  the archived-run lookup, and it hands back the byte length the
   *  incremental tail resumes from. */
  const load = useCallback(async () => {
    setLoading(true);
    // Drop the previous source's lines immediately. Without this the screen
    // shows the old run's contents under the new run's heading for as long as
    // the sidecar takes to answer, and an in-flight poll can briefly append to
    // them.
    setTail(emptyTail);
    try {
      const r = await readLoaderLog({
        lines: LINE_CAP,
        prev: readPrev,
        run: source.kind === 'run' ? source.name : undefined,
        // Session slicing happens client-side over the whole buffer, so the
        // view stays right when the game starts a new session mid-follow.
        allSessions: true,
      });
      setMeta(r);
      setTail(
        r
          ? {
              // `bytes` is absent on an older sidecar; a null offset makes the
              // first poll re-read a window and replace the buffer rather than
              // duplicate it.
              offset: typeof r.bytes === 'number' ? r.bytes : null,
              lines: r.lines,
              truncated: r.truncated,
            }
          : emptyTail,
      );
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [source, readPrev]);

  useEffect(() => {
    void load();
  }, [load]);

  // A game starting while "Current run" sits empty: read the new log from the
  // start rather than tailing on from the finished run's buffer.
  const wasUp = useRef(gameUp);
  useEffect(() => {
    const started = gameUp && !wasUp.current;
    wasUp.current = gameUp;
    if (started && followable) void load();
  }, [gameUp, followable, load]);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await loaderHealth());
    } catch {
      // A missing or unreadable health file is not worth an error state on a
      // screen whose job is showing the log.
      setHealth(null);
    }
  }, []);

  // Re-read when the game stops: that is exactly when a canary opened by a
  // crashy boot becomes visible.
  // Read on mount, and again each time the game stops. This was two effects
  // that both fired on mount, so opening the Log screen read the health file twice.
  const healthRead = useRef(false);
  useEffect(() => {
    const first = !healthRead.current;
    healthRead.current = true;
    if (first || !running) void refreshHealth();
  }, [running, refreshHealth]);

  const refreshRuns = useCallback(async () => {
    try {
      const r = await listLoaderRuns();
      setRuns(r?.runs ?? []);
      setRunsDir(r?.dir ?? null);
    } catch {
      setRuns([]);
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  const onOpenFolder = async () => {
    if (!runsDir) return;
    try {
      await openLoaderLogsDir(runsDir);
    } catch (e) {
      toast.push(e instanceof Error ? e.message : String(e), 'error');
    }
  };

  const onDeleteLogs = async () => {
    if (!runsDir) return;
    const ok = await dialog.confirm({
      title: t('Delete all logs?'),
      body: gameUp
        ? t(
            'This deletes every archived run. The log of the game that is running now is kept until it closes.',
          )
        : t(
            'This deletes every archived run and the last run’s log. Logs you have already shared keep working.',
          ),
      confirmLabel: t('Delete'),
      destructive: true,
    });
    if (!ok) return;
    try {
      const r = await deleteLoaderLogs(runsDir, !gameUp);
      toast.push(
        t.n(r.files, 'Deleted {n} log file.', 'Deleted {n} log files.'),
        r.skipped > 0 ? 'error' : 'success',
      );
      setSource({ kind: 'current' });
      await refreshRuns();
      await load();
    } catch (e) {
      toast.push(e instanceof Error ? e.message : String(e), 'error');
    }
  };

  /**
   * The follow loop.
   *
   * Gated on document visibility as well as the Follow toggle: a minimised or
   * background window has nobody reading it, and a timer that keeps firing
   * there is pure cost — it was the reason the app kept working the disk while
   * the user was in the game.
   */
  useEffect(() => {
    if (!follow || !followable || !meta?.path) return;
    let stopped = false;

    const poll = async () => {
      if (stopped || document.visibilityState !== 'visible') return;
      const current = tailRef.current;
      try {
        const chunk: LogChunk = await readLoaderLogChunk(meta.path, current.offset);
        if (stopped) return;
        // A null offset means we have no trustworthy resume point, so the
        // chunk is the whole window and replaces the buffer.
        setTail(appendChunk(current.offset === null ? emptyTail : current, chunk, LINE_CAP));
      } catch {
        // A transient read failure (the game rotating the file under us) is
        // not worth tearing the screen down for; the next tick retries.
      }
    };

    const handle = window.setInterval(() => void poll(), POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void poll();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      stopped = true;
      window.clearInterval(handle);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [follow, followable, meta?.path]);

  const buffered = useMemo(() => sessionSlice(tail.lines, allSessions), [tail.lines, allSessions]);
  const lines = useMemo(() => parseLoaderLog(buffered), [buffered]);
  const tags = useMemo(() => loaderLogTags(lines), [lines]);
  const problems = useMemo(() => loaderLogProblems(lines), [lines]);
  const sessions = useMemo(
    () => buffered.filter((l) => l.includes('== SESSION ')).length,
    [buffered],
  );

  const needle = query.trim().toLowerCase();
  const visible = lines.filter((line) => {
    if (problemsOnly && !line.severity && line.kind !== 'session') return false;
    if (tag !== 'all' && line.tag !== tag) return false;
    if (!needle) return true;
    return line.raw.toLowerCase().includes(needle);
  });

  // Only auto-scroll when the user is already at the bottom — yanking the
  // view down while they are reading back through a crash is worse than not
  // following at all.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-pin whenever the rendered set changes
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !follow || !pinnedToBottom.current) return;
    el.scrollTop = el.scrollHeight;
  }, [visible.length, follow]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  const onReEnable = async (modId: string) => {
    try {
      await resetModHealth(modId);
      toast.push(t('{mod} will load again on the next launch.', { mod: modId }), 'success');
      await refreshHealth();
    } catch (e) {
      toast.push(e instanceof Error ? e.message : String(e), 'error');
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t('Log')}
        subtitle={t('What the script loader wrote inside the game, live.')}
      />

      <HealthBanner health={health} onReEnable={onReEnable} />

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-fraktur text-xl text-parchment">{sourceLabel(source, t)}</h3>
            {gameUp && followable ? (
              <MonoTag tone="gilt">{t('game running')}</MonoTag>
            ) : idle ? null : meta?.exists ? (
              <MonoTag>{t.n(sessions, '{n} session', '{n} sessions')}</MonoTag>
            ) : null}
            {tail.truncated ? <MonoTag>{t('oldest lines trimmed')}</MonoTag> : null}
            {problems.errors > 0 ? (
              <MonoTag tone="crimson">{t.n(problems.errors, '{n} error', '{n} errors')}</MonoTag>
            ) : null}
            {problems.warnings > 0 ? (
              <MonoTag>{t.n(problems.warnings, '{n} warning', '{n} warnings')}</MonoTag>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              disabled={!followable}
              variant={follow && followable ? 'gilt' : 'default'}
              onClick={() => setFollow((f) => !f)}
              title={
                followable
                  ? follow
                    ? t('Stop watching the log file')
                    : t('Watch the log file for new lines')
                  : t('A finished run never changes — nothing to follow')
              }
            >
              {follow && followable ? (
                <Pause className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <Play className="h-3.5 w-3.5" aria-hidden />
              )}
              {follow && followable ? t('Following') : t('Paused')}
            </Button>
            <Button type="button" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              {t('Refresh')}
            </Button>
            <CopyButton value={buffered.join('\n')} />
            <Button
              type="button"
              size="sm"
              disabled={!meta?.exists || buffered.length === 0}
              onClick={() => setSharing({ lines: buffered, path: meta?.path ?? null })}
              title={t('Upload this log and get a link to paste into a bug report')}
            >
              <Link2 className="h-3.5 w-3.5" aria-hidden />
              {t('Share link')}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!runsDir}
              onClick={() => void onOpenFolder()}
              title={t('Open the folder that holds every archived run')}
            >
              <FolderOpen className="h-3.5 w-3.5" aria-hidden />
              {t('Open folder')}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!runsDir}
              onClick={() => void onDeleteLogs()}
              title={t('Delete the archived runs and the last run’s log')}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              {t('Delete logs')}
            </Button>
          </div>
        </div>

        <Fleuron className="my-3" />

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Select
            value={
              source.kind === 'run'
                ? `run:${source.name}`
                : source.kind === 'current'
                  ? 'now'
                  : source.kind
            }
            onChange={(v) =>
              setSource(
                v === 'now'
                  ? { kind: 'current' }
                  : v === 'last'
                    ? { kind: 'last' }
                    : { kind: 'run', name: v.slice('run:'.length) },
              )
            }
            ariaLabel={t('Which run to read')}
          >
            <option value="now">{t('Current run')}</option>
            {/* The loader archives a run when the NEXT one starts, so with no
                game up the newest log is the one finished run the archive below
                does not hold yet. While a game runs, that run is the newest
                archive entry, and a second "previous" entry only repeated it. */}
            {!gameUp || source.kind === 'last' ? (
              <option value="last">{t('Last run')}</option>
            ) : null}
            {runs.map((r) => (
              <option key={r.name} value={`run:${r.name}`}>
                {r.name.replace(/\.log$/, '')} · {Math.max(1, Math.round(r.bytes / 1024))} KB
              </option>
            ))}
          </Select>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('Search the log...')}
            className="font-data min-w-56 flex-1 border border-border bg-pitch/60 px-3 py-2 text-sm text-parchment placeholder:text-ash focus:border-gilt/60 focus:outline-none"
          />
          <Select value={tag} onChange={setTag} ariaLabel={t('Filter by subsystem')}>
            <option value="all">{t('All subsystems')}</option>
            {tags.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
          <label className="font-mono flex cursor-pointer items-center gap-2 text-xs text-ash">
            <input
              type="checkbox"
              checked={problemsOnly}
              onChange={(e) => setProblemsOnly(e.target.checked)}
              className="h-3.5 w-3.5 accent-crimson"
            />
            {t('problems only')}
          </label>
          <label className="font-mono flex cursor-pointer items-center gap-2 text-xs text-ash">
            <input
              type="checkbox"
              checked={allSessions}
              onChange={(e) => setAllSessions(e.target.checked)}
              className="h-3.5 w-3.5 accent-crimson"
            />
            {t('all sessions')}
          </label>
        </div>

        {problemsOnly ? (
          <p className="font-serif-italic mb-2 text-xs text-ash">
            {t(
              'Showing lines the loader flagged. Only failures it was taught to classify carry a tag, so an unflagged line means “not classified”, not “fine”.',
            )}
          </p>
        ) : null}

        {idle ? (
          <div className="border border-border bg-pitch/60 p-3">
            <p className="font-serif-italic text-ash">
              {t('Ravenswatch is not running. Its log shows here as soon as you start it.')}
            </p>
            {meta?.exists ? (
              <Button
                type="button"
                size="sm"
                className="mt-2"
                onClick={() => setSource({ kind: 'last' })}
              >
                {t('Show the last run')}
              </Button>
            ) : null}
          </div>
        ) : (
          <LogBody
            loading={loading}
            error={error}
            meta={meta}
            lines={visible}
            total={lines.length}
            scrollRef={scrollRef}
            onScroll={onScroll}
          />
        )}

        {meta?.path ? (
          <p className="font-data mt-2 break-all text-xs text-ash">{meta.path}</p>
        ) : null}
      </Panel>

      {sharing ? (
        <ShareLogDialog
          loaderLines={sharing.lines}
          loaderPath={sharing.path}
          onClose={() => setSharing(null)}
        />
      ) : null}
    </div>
  );
}

/**
 * What the loader recorded about crashy boots.
 *
 * `health.cpp` opens a canary before any mod code runs, stamps it as each
 * `init.lua` executes, and disables a mod after three consecutive failed
 * boots. That verdict was reachable from `rsmm doctor` and from nowhere in the
 * app, so a quarantined mod looked simply "off" — with no way to tell that the
 * loader had switched it off, why, or how to undo it.
 */
function HealthBanner({
  health,
  onReEnable,
}: {
  health: LoaderHealth | null;
  onReEnable: (modId: string) => void | Promise<void>;
}) {
  const t = useT();
  if (!health?.exists) return null;
  const disabled = health.mods.filter((m) => m.disabled);
  const canary = health.canary;
  if (!canary && disabled.length === 0) return null;

  return (
    <Panel className="border-crimson/50 bg-crimson/5">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-crimson" aria-hidden />
        <div className="min-w-0 flex-1 space-y-3">
          {canary ? (
            <div>
              <h3 className="font-fraktur text-lg text-parchment">
                {t('The last launch did not finish starting up')}
              </h3>
              <p className="font-serif-italic mt-1 text-sm text-ash">
                {canary.blamedMod ? (
                  <TParts
                    text={t(
                      'The game stopped while {mod} was loading. The log below is from that run.',
                    )}
                    parts={{
                      mod: <strong className="text-parchment">{canary.blamedMod}</strong>,
                    }}
                  />
                ) : (
                  t(
                    'The game stopped before any mod ran ({step}), so this is the loader or the game itself rather than one of your mods.',
                    { step: canary.step || t('boot') },
                  )
                )}
              </p>
            </div>
          ) : null}

          {disabled.length > 0 ? (
            <div>
              <h3 className="font-fraktur text-lg text-parchment">
                {t.n(
                  disabled.length,
                  'A mod was switched off by the loader',
                  '{n} mods were switched off by the loader',
                )}
              </h3>
              <p className="font-serif-italic mt-1 text-sm text-ash">
                {t(
                  'A mod that crashes the game during startup cannot be turned off from inside it, so the loader skips it after {n} failed launches in a row.',
                  { n: health.threshold },
                )}
              </p>
              <ul className="mt-2 space-y-2">
                {disabled.map((m) => (
                  <li
                    key={m.id}
                    className="flex flex-wrap items-center gap-2 border border-border bg-pitch/60 px-3 py-2"
                  >
                    <span className="font-data text-sm text-parchment">{m.id}</span>
                    <span className="font-serif-italic min-w-0 flex-1 text-xs text-ash">
                      {m.disabledReason || t('{n} failed launches', { n: m.crashes })}
                      {m.lastError ? ` — ${m.lastError}` : ''}
                    </span>
                    <Button type="button" size="sm" onClick={() => void onReEnable(m.id)}>
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                      {t('Try again')}
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}

function Select({
  value,
  onChange,
  ariaLabel,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  ariaLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div className="relative inline-flex">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={ariaLabel}
        className="select-grim font-data max-w-64 appearance-none truncate border border-border bg-pitch/60 py-2 pl-3 pr-9 text-sm text-parchment focus:border-gilt/60 focus:outline-none"
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ash"
        aria-hidden="true"
      />
    </div>
  );
}

function LogBody({
  loading,
  error,
  meta,
  lines,
  total,
  scrollRef,
  onScroll,
}: {
  loading: boolean;
  error: string | null;
  meta: LoaderLogResult | null;
  lines: LoaderLogLine[];
  total: number;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
}) {
  const t = useT();
  if (loading && !meta) {
    return <p className="font-serif-italic text-ash">{t('Reading the loader log…')}</p>;
  }
  if (error) {
    // `explainError` returns English sources — see lib/errors.
    const { title, hint } = explainError(error);
    return (
      <div className="border border-crimson/50 bg-crimson/10 p-3">
        <p className="font-serif-italic text-parchment">{t(title)}</p>
        {hint ? <p className="font-serif-italic mt-1 text-sm text-ash">{t(hint)}</p> : null}
      </div>
    );
  }
  if (!meta?.exists) {
    return (
      <p className="font-serif-italic border border-border bg-pitch/60 p-3 text-ash">
        {t(
          'No loader log yet. It appears the first time you launch Modded with the script loader installed — asset and texture mods work without it and never write here.',
        )}
      </p>
    );
  }
  if (lines.length === 0) {
    return (
      <p className="font-serif-italic border border-border bg-pitch/60 p-3 text-ash">
        {total > 0
          ? t('No lines match the current filters.')
          : t('The log is empty for this run — the loader attached but wrote nothing.')}
      </p>
    );
  }
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="max-h-[60vh] overflow-auto border border-border bg-pitch/60"
    >
      <ul className="divide-y divide-border/40">
        {lines.map((line, i) => (
          // Loader lines repeat verbatim (a poll loop logging the same probe),
          // so position is part of the identity.
          <li
            key={`${i}-${line.raw}`}
            className="px-3 py-1"
            // Rows wrap, so their heights vary and a fixed-height virtual list
            // would mis-measure them. `content-visibility` lets the browser
            // skip layout and paint for rows outside the viewport while still
            // measuring the ones on screen honestly; the intrinsic size is the
            // scrollbar's estimate for what it skipped.
            style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 28px' }}
          >
            {line.kind === 'session' ? (
              <p className="font-data text-xs text-gilt">{line.message}</p>
            ) : (
              <div className="flex flex-wrap items-baseline gap-2">
                {line.stamp ? (
                  <span className="font-mono shrink-0 text-xs text-ash">
                    {line.stamp.slice(11)}
                  </span>
                ) : null}
                {line.severity ? (
                  <span
                    className={`font-mono shrink-0 border px-1 text-xs uppercase ${
                      line.severity === 'err'
                        ? 'border-crimson/60 text-crimson'
                        : 'border-gilt/50 text-gilt'
                    }`}
                  >
                    {line.severity}
                  </span>
                ) : null}
                {line.tag ? (
                  <span className="font-mono shrink-0 border border-border px-1 text-xs text-smoke">
                    {line.tag}
                  </span>
                ) : null}
                <span
                  className={`min-w-0 break-words text-sm ${
                    line.severity === 'err' || line.kind === 'raw'
                      ? 'text-crimson'
                      : line.severity === 'warn'
                        ? 'text-gilt'
                        : 'text-parchment/90'
                  }`}
                >
                  {line.message}
                </span>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
