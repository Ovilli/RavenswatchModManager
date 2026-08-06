import { createFileRoute } from '@tanstack/react-router';
import { ChevronDown, Pause, Play, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button, CopyButton, Fleuron, MonoTag, Panel, SectionHeader } from '../components/chrome';
import { useLaunch } from '../components/launch';
import { explainError } from '../lib/errors';
import { type LoaderLogLine, loaderLogTags, parseLoaderLog } from '../lib/loader-log';
import { type LoaderLogResult, readLoaderLog } from '../lib/rsmm';

export const Route = createFileRoute('/log')({
  component: LogPage,
});

/** Poll cadence while following. The loader writes a line per event, not a
 * stream, so a second is plenty and keeps the sidecar spawn rate sane. */
const POLL_MS = 1000;
const LINE_CAP = 1000;

function LogPage() {
  const { running } = useLaunch();
  const [result, setResult] = useState<LoaderLogResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [follow, setFollow] = useState(true);
  const [allSessions, setAllSessions] = useState(false);
  const [prev, setPrev] = useState(false);
  const [query, setQuery] = useState('');
  const [tag, setTag] = useState('all');
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);

  const load = useCallback(async () => {
    try {
      const r = await readLoaderLog({ lines: LINE_CAP, prev, allSessions });
      setResult(r);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [prev, allSessions]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  useEffect(() => {
    if (!follow) return;
    const handle = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(handle);
  }, [follow, load]);

  const lines = useMemo(() => parseLoaderLog(result?.lines ?? []), [result]);
  const tags = useMemo(() => loaderLogTags(lines), [lines]);
  const needle = query.trim().toLowerCase();
  const visible = lines.filter((line) => {
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

  return (
    <div className="space-y-6">
      <SectionHeader title="Log" subtitle="What the script loader wrote inside the game, live." />

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h3 className="font-fraktur text-xl text-parchment">
              {prev ? 'Previous run' : 'Current run'}
            </h3>
            {running ? (
              <MonoTag tone="gilt">game running</MonoTag>
            ) : result?.exists ? (
              <MonoTag>
                {result.sessions} session{result.sessions === 1 ? '' : 's'}
              </MonoTag>
            ) : null}
            {result?.truncated ? <MonoTag>oldest lines trimmed</MonoTag> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant={follow ? 'gilt' : 'default'}
              onClick={() => setFollow((f) => !f)}
              title={follow ? 'Stop polling the log file' : 'Poll the log file for new lines'}
            >
              {follow ? (
                <Pause className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <Play className="h-3.5 w-3.5" aria-hidden />
              )}
              {follow ? 'Following' : 'Paused'}
            </Button>
            <Button type="button" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Refresh
            </Button>
            <CopyButton value={(result?.lines ?? []).join('\n')} />
          </div>
        </div>

        <Fleuron className="my-3" />

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search the log..."
            className="font-mono min-w-56 flex-1 border border-border bg-pitch/60 px-3 py-2 text-sm text-parchment placeholder:text-ash focus:border-gilt/60 focus:outline-none"
          />
          <div className="relative inline-flex">
            <select
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              aria-label="Filter by subsystem"
              className="select-grim font-mono appearance-none border border-border bg-pitch/60 py-2 pl-3 pr-9 text-sm text-parchment focus:border-gilt/60 focus:outline-none"
            >
              <option value="all">All subsystems</option>
              {tags.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <ChevronDown
              className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ash"
              aria-hidden="true"
            />
          </div>
          <label className="font-mono flex cursor-pointer items-center gap-2 text-xs text-ash">
            <input
              type="checkbox"
              checked={allSessions}
              onChange={(e) => setAllSessions(e.target.checked)}
              className="h-3.5 w-3.5 accent-crimson"
            />
            all sessions
          </label>
          <label className="font-mono flex cursor-pointer items-center gap-2 text-xs text-ash">
            <input
              type="checkbox"
              checked={prev}
              onChange={(e) => setPrev(e.target.checked)}
              className="h-3.5 w-3.5 accent-crimson"
            />
            previous run
          </label>
        </div>

        <LogBody
          loading={loading}
          error={error}
          result={result}
          lines={visible}
          total={lines.length}
          scrollRef={scrollRef}
          onScroll={onScroll}
        />

        {result?.path ? (
          <p className="font-mono mt-2 break-all text-[10px] text-ash">{result.path}</p>
        ) : null}
      </Panel>
    </div>
  );
}

function LogBody({
  loading,
  error,
  result,
  lines,
  total,
  scrollRef,
  onScroll,
}: {
  loading: boolean;
  error: string | null;
  result: LoaderLogResult | null;
  lines: LoaderLogLine[];
  total: number;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
}) {
  if (loading && !result) {
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
  if (!result?.exists) {
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
          <li key={`${i}-${line.raw}`} className="px-3 py-1">
            {line.kind === 'session' ? (
              <p className="font-mono text-xs text-gilt">{line.message}</p>
            ) : (
              <div className="flex flex-wrap items-baseline gap-2">
                {line.stamp ? (
                  <span className="font-mono shrink-0 text-[10px] text-ash">
                    {line.stamp.slice(11)}
                  </span>
                ) : null}
                {line.tag ? (
                  <span className="font-mono shrink-0 border border-border px-1 text-[10px] text-smoke">
                    {line.tag}
                  </span>
                ) : null}
                <span
                  className={`min-w-0 break-words text-sm ${
                    line.kind === 'raw' ? 'text-crimson' : 'text-parchment/90'
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
