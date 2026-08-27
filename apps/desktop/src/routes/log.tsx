import { createFileRoute } from '@tanstack/react-router';
import { AlertTriangle, ChevronDown, Link2, Pause, Play, RefreshCw, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, CopyButton, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { useLaunch } from '../components/launch';
import { ShareLogDialog } from '../components/share-log-dialog';
import { useToast } from '../components/toast';
import { explainError } from '../lib/errors';
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
  emptyTail,
  readLoaderLogChunk,
  sessionSlice,
} from '../lib/loader-log-tail';
import {
  type ArchivedRun,
  type LoaderHealth,
  type LoaderLogResult,
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
type Source = { kind: 'current' } | { kind: 'prev' } | { kind: 'run'; name: string };

function sourceLabel(source: Source): string {
  if (source.kind === 'current') return 'Current run';
  if (source.kind === 'prev') return 'Previous run';
  return source.name.replace(/\.log$/, '');
}

function LogPage() {
  const { running } = useLaunch();
  const toast = useToast();
  const [source, setSource] = useState<Source>({ kind: 'current' });
  const [runs, setRuns] = useState<ArchivedRun[]>([]);
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
        prev: source.kind === 'prev',
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
  }, [source]);

  useEffect(() => {
    void load();
  }, [load]);

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
  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);
  useEffect(() => {
    if (!running) void refreshHealth();
  }, [running, refreshHealth]);

  useEffect(() => {
    void listLoaderRuns()
      .then((r) => setRuns(r?.runs ?? []))
      .catch(() => setRuns([]));
  }, []);

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
      toast.push(`${modId} will load again on the next launch.`, 'success');
      await refreshHealth();
    } catch (e) {
      toast.push(e instanceof Error ? e.message : String(e), 'error');
    }
  };

  return (
    <div className="space-y-6">
      <SectionHeader title="Log" subtitle="What the script loader wrote inside the game, live." />

      <HealthBanner health={health} onReEnable={onReEnable} />

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-fraktur text-xl text-parchment">{sourceLabel(source)}</h3>
            {running && followable ? (
              <MonoTag tone="gilt">game running</MonoTag>
            ) : meta?.exists ? (
              <MonoTag>
                {sessions} session{sessions === 1 ? '' : 's'}
              </MonoTag>
            ) : null}
            {tail.truncated ? <MonoTag>oldest lines trimmed</MonoTag> : null}
            {problems.errors > 0 ? (
              <MonoTag tone="crimson">
                {problems.errors} error{problems.errors === 1 ? '' : 's'}
              </MonoTag>
            ) : null}
            {problems.warnings > 0 ? <MonoTag>{problems.warnings} warnings</MonoTag> : null}
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
                    ? 'Stop watching the log file'
                    : 'Watch the log file for new lines'
                  : 'A finished run never changes — nothing to follow'
              }
            >
              {follow && followable ? (
                <Pause className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <Play className="h-3.5 w-3.5" aria-hidden />
              )}
              {follow && followable ? 'Following' : 'Paused'}
            </Button>
            <Button type="button" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Refresh
            </Button>
            <CopyButton value={buffered.join('\n')} />
            <Button
              type="button"
              size="sm"
              disabled={!meta?.exists || buffered.length === 0}
              onClick={() => setSharing({ lines: buffered, path: meta?.path ?? null })}
              title="Upload this log and get a link to paste into a bug report"
            >
              <Link2 className="h-3.5 w-3.5" aria-hidden />
              Share link
            </Button>
          </div>
        </div>

        <Fleuron className="my-3" />

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Select
            value={
              source.kind === 'run' ? `run:${source.name}` : source.kind === 'prev' ? 'prev' : 'now'
            }
            onChange={(v) =>
              setSource(
                v === 'now'
                  ? { kind: 'current' }
                  : v === 'prev'
                    ? { kind: 'prev' }
                    : { kind: 'run', name: v.slice('run:'.length) },
              )
            }
            ariaLabel="Which run to read"
          >
            <option value="now">Current run</option>
            <option value="prev">Previous run</option>
            {runs.map((r) => (
              <option key={r.name} value={`run:${r.name}`}>
                {r.name.replace(/\.log$/, '')} · {Math.max(1, Math.round(r.bytes / 1024))} KB
              </option>
            ))}
          </Select>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search the log..."
            className="font-mono min-w-56 flex-1 border border-border bg-pitch/60 px-3 py-2 text-sm text-parchment placeholder:text-ash focus:border-gilt/60 focus:outline-none"
          />
          <Select value={tag} onChange={setTag} ariaLabel="Filter by subsystem">
            <option value="all">All subsystems</option>
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
            problems only
          </label>
          <label className="font-mono flex cursor-pointer items-center gap-2 text-xs text-ash">
            <input
              type="checkbox"
              checked={allSessions}
              onChange={(e) => setAllSessions(e.target.checked)}
              className="h-3.5 w-3.5 accent-crimson"
            />
            all sessions
          </label>
        </div>

        {problemsOnly ? (
          <p className="font-serif-italic mb-2 text-xs text-ash">
            Showing lines the loader flagged. Only failures it was taught to classify carry a tag,
            so an unflagged line means “not classified”, not “fine”.
          </p>
        ) : null}

        <LogBody
          loading={loading}
          error={error}
          meta={meta}
          lines={visible}
          total={lines.length}
          scrollRef={scrollRef}
          onScroll={onScroll}
        />

        {meta?.path ? (
          <p className="font-mono mt-2 break-all text-[10px] text-ash">{meta.path}</p>
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
                The last launch did not finish starting up
              </h3>
              <p className="font-serif-italic mt-1 text-sm text-ash">
                {canary.blamedMod ? (
                  <>
                    The game stopped while{' '}
                    <strong className="text-parchment">{canary.blamedMod}</strong> was loading. The
                    log below is from that run.
                  </>
                ) : (
                  <>
                    The game stopped before any mod ran ({canary.step || 'boot'}), so this is the
                    loader or the game itself rather than one of your mods.
                  </>
                )}
              </p>
            </div>
          ) : null}

          {disabled.length > 0 ? (
            <div>
              <h3 className="font-fraktur text-lg text-parchment">
                {disabled.length === 1
                  ? 'A mod was switched off by the loader'
                  : `${disabled.length} mods were switched off by the loader`}
              </h3>
              <p className="font-serif-italic mt-1 text-sm text-ash">
                A mod that crashes the game during startup cannot be turned off from inside it, so
                the loader skips it after {health.threshold} failed launches in a row.
              </p>
              <ul className="mt-2 space-y-2">
                {disabled.map((m) => (
                  <li
                    key={m.id}
                    className="flex flex-wrap items-center gap-2 border border-border bg-pitch/60 px-3 py-2"
                  >
                    <span className="font-mono text-sm text-parchment">{m.id}</span>
                    <span className="font-serif-italic min-w-0 flex-1 text-xs text-ash">
                      {m.disabledReason || `${m.crashes} failed launches`}
                      {m.lastError ? ` — ${m.lastError}` : ''}
                    </span>
                    <Button type="button" size="sm" onClick={() => void onReEnable(m.id)}>
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                      Try again
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
        className="select-grim font-mono max-w-64 appearance-none truncate border border-border bg-pitch/60 py-2 pl-3 pr-9 text-sm text-parchment focus:border-gilt/60 focus:outline-none"
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
  if (loading && !meta) {
    return <p className="font-serif-italic text-ash">Reading the loader log…</p>;
  }
  if (error) {
    const { title, hint } = explainError(error);
    return (
      <div className="border border-crimson/50 bg-crimson/10 p-3">
        <p className="font-serif-italic text-parchment">{title}</p>
        {hint ? <p className="font-serif-italic mt-1 text-sm text-ash">{hint}</p> : null}
      </div>
    );
  }
  if (!meta?.exists) {
    return (
      <p className="font-serif-italic border border-border bg-pitch/60 p-3 text-ash">
        No loader log yet. It appears the first time you launch Modded with the script loader
        installed — asset and texture mods work without it and never write here.
      </p>
    );
  }
  if (lines.length === 0) {
    return (
      <p className="font-serif-italic border border-border bg-pitch/60 p-3 text-ash">
        {total > 0
          ? 'No lines match the current filters.'
          : 'The log is empty for this run — the loader attached but wrote nothing.'}
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
              <p className="font-mono text-xs text-gilt">{line.message}</p>
            ) : (
              <div className="flex flex-wrap items-baseline gap-2">
                {line.stamp ? (
                  <span className="font-mono shrink-0 text-[10px] text-ash">
                    {line.stamp.slice(11)}
                  </span>
                ) : null}
                {line.severity ? (
                  <span
                    className={`font-mono shrink-0 border px-1 text-[10px] uppercase ${
                      line.severity === 'err'
                        ? 'border-crimson/60 text-crimson'
                        : 'border-gilt/50 text-gilt'
                    }`}
                  >
                    {line.severity}
                  </span>
                ) : null}
                {line.tag ? (
                  <span className="font-mono shrink-0 border border-border px-1 text-[10px] text-smoke">
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
