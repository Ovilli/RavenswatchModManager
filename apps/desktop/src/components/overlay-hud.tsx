/**
 * A mod's overlay — a frameless always-on-top HUD, in the client's own
 * Grimoire styling.
 *
 * Nothing here knows what any particular mod measures. The mod's manifest
 * declares the shape (title, icon, columns, sorting, highlight) and its Lua
 * publishes rows; this renders that declaration. Shape is data, never code: a
 * mod cannot hand markup or script to this webview, which can spawn the CLI —
 * mod-supplied code here would be arbitrary code execution on the player's
 * machine, and every overlay would look like whatever its author felt like.
 *
 * Runs in its own webview window (see lib/overlay-windows.ts), rendered by
 * main.tsx WITHOUT the app chrome.
 */
import { isTauri } from '@tauri-apps/api/core';
import { emit, listen } from '@tauri-apps/api/event';
import { LogicalSize, getCurrentWindow } from '@tauri-apps/api/window';
import {
  Activity,
  Flame,
  Gauge,
  Heart,
  List,
  Maximize2,
  Minimize2,
  MousePointerClick,
  Pin,
  Shield,
  Skull,
  Star,
  Swords,
  Timer,
  Trophy,
  X,
  Zap,
} from 'lucide-react';
import { GripHorizontal } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useT } from '../lib/i18n-react';
import { savePosition } from '../lib/overlay-windows';
import { type OverlayColumn, type OverlayRecord, listOverlays } from '../lib/rsmm';
import { attachSmoothWheel } from '../lib/smooth-scroll';

/** How often the data is re-read. Mods publish at their own cadence. */
const POLL_MS = 1000;
/** A publish older than this means nothing is playing right now. */
const STALE_AFTER_S = 20;

/** Event the main window emits to hand input back after click-through. */
export const OVERLAY_INTERACTIVE_EVENT = 'rsmm://overlay-interactive';

/** The icon allowlist, mirroring `ICONS` in cmd_overlay.py. */
const ICONS = {
  activity: Activity,
  flame: Flame,
  gauge: Gauge,
  heart: Heart,
  list: List,
  shield: Shield,
  skull: Skull,
  star: Star,
  swords: Swords,
  timer: Timer,
  trophy: Trophy,
  zap: Zap,
} as const;

/**
 * `?demo=1` fills the overlay with sample rows and skips the CLI. A HUD has to
 * be judged with numbers in it, and "start the game, join a co-op run, fight
 * something" is a poor edit/preview loop.
 */
const DEMO: OverlayRecord = {
  modId: 'demo',
  modName: 'Demo',
  enabled: true,
  title: 'Damage',
  icon: 'swords',
  columns: [
    { key: 'label', label: 'Player', type: 'text', format: 'plain', suffix: '' },
    { key: 'dealt', label: 'Damage', type: 'number', format: 'compact', suffix: '' },
    { key: 'share', label: 'Share', type: 'bar', format: 'plain', suffix: '' },
    { key: 'pct', label: '%', type: 'percent', format: 'plain', suffix: '' },
    { key: 'dps', label: 'DPS', type: 'number', format: 'compact', suffix: '/s' },
  ],
  sort: { key: 'dealt', dir: 'desc' },
  highlight: 'is_local',
  empty: 'Waiting for a run.',
  rows: [
    { label: 'You', dealt: 48210, share: 0.573, pct: 0.573, dps: 612.4, is_local: true },
    { label: 'Ada', dealt: 31904, share: 0.379, pct: 0.379, dps: 402.1, is_local: false },
    { label: 'Player 3', dealt: 4055, share: 0.048, pct: 0.048, dps: 51.7, is_local: false },
  ],
  meta: { total: 84169, window: 10 },
  updated: Math.floor(Date.now() / 1000),
  exists: true,
};

function compactNumber(n: number): string {
  if (!Number.isFinite(n)) return '0';
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}m`;
  if (Math.abs(n) >= 10_000) return `${(n / 1000).toFixed(0)}k`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return n.toFixed(0);
}

function Cell({
  column,
  value,
}: { column: OverlayColumn; value: string | number | boolean | undefined }) {
  if (value === undefined || value === null) return <span className="flex-1" />;

  if (column.type === 'bar') {
    const pct = Math.max(0, Math.min(1, Number(value) || 0));
    return (
      <span className="relative h-1.5 w-12 shrink-0 overflow-hidden rounded-sm bg-char/40">
        <span
          className="absolute inset-y-0 left-0 bg-crimson transition-[width] duration-500 ease-grimoire"
          style={{ width: `${pct * 100}%` }}
        />
      </span>
    );
  }
  if (column.type === 'text') {
    // The name column takes the slack and is the LAST thing to be truncated:
    // "Player" cut to "Play…" is useless, and a fixed-width number column
    // stealing space from it is how that happened.
    return (
      <span className="min-w-[4.5rem] flex-1 truncate text-sm" title={String(value)}>
        {String(value)}
      </span>
    );
  }
  const num = Number(value);
  const text = Number.isFinite(num)
    ? column.type === 'percent'
      ? `${(num * 100).toFixed(0)}%`
      : (column.format === 'compact' ? compactNumber(num) : num.toLocaleString()) + column.suffix
    : String(value);
  // No fixed width: a number column is exactly as wide as its widest value,
  // so the name keeps everything left over.
  return (
    <span className="font-mono shrink-0 whitespace-nowrap text-right text-[0.72rem] tabular-nums">
      {text}
    </span>
  );
}

export function OverlayHud({ modId }: { modId: string }) {
  const t = useT();
  const [record, setRecord] = useState<OverlayRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compact, setCompact] = useState(false);
  const [clickThrough, setClickThrough] = useState(false);
  const inFlight = useRef(false);
  const prevOrder = useRef<Record<string, number>>({});
  // Height we asked the window for, so a resize event can be told apart from
  // one the PLAYER performed. Once they size it by hand, auto-fit backs off
  // for good — nothing is ruder than a window that fights the mouse.
  const autoHeight = useRef<number | null>(null);
  const [manualSize, setManualSize] = useState(false);
  const body = useRef<HTMLDivElement | null>(null);
  const demo = new URLSearchParams(window.location.search).get('demo') === '1';
  // Outside the Tauri shell there is no window to drive and no sidecar to
  // call; the component still renders so the design can be previewed.
  const native = isTauri();

  // The window paints its own card; the app's page background would otherwise
  // fill the frame and defeat `transparent: true`.
  useEffect(() => {
    const html = document.documentElement;
    const prevHtml = html.style.background;
    const prevBody = document.body.style.background;
    html.style.background = 'transparent';
    document.body.style.background = 'transparent';
    document.body.style.overflow = 'hidden';
    return () => {
      html.style.background = prevHtml;
      document.body.style.background = prevBody;
    };
  }, []);

  const poll = useCallback(async () => {
    if (demo) {
      setRecord(DEMO);
      return;
    }
    if (!native || inFlight.current) return;
    inFlight.current = true;
    try {
      const list = await listOverlays();
      const found = list?.overlays.find((o) => o.modId === modId) ?? null;
      setRecord(found);
      setError(found ? null : `no installed mod "${modId}" declares an overlay`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
    }
  }, [demo, native, modId]);

  useEffect(() => {
    void poll();
    const id = setInterval(() => void poll(), POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  // Same wheel smoothing as the main window. This is a SECOND window rendering
  // this component directly — it never mounts the app root — so it has to
  // attach its own, or the one panel a player reads mid-run is the one that
  // still scrolls in teleporting jumps.
  useEffect(() => attachSmoothWheel(document), []);

  // Remember where the player put it, and how big they made it.
  useEffect(() => {
    if (!native) return;
    const win = getCurrentWindow();
    const persist = async () => {
      try {
        const pos = await win.outerPosition();
        const size = await win.outerSize();
        savePosition(modId, { x: pos.x, y: pos.y, width: size.width, height: size.height });
      } catch {
        // Position is a convenience; never let it break the overlay.
      }
    };
    const unlistenMove = win.onMoved(() => void persist());
    const unlistenResize = win.onResized(({ payload }) => {
      void (async () => {
        const expected = autoHeight.current;
        // Before the first auto-fit there is nothing to compare against, and
        // the window manager raises a resize when the window is first shown.
        // Treating THAT as "the player resized it" latched auto-fit off on
        // frame one and left the empty pane this exists to remove — so a
        // resize only counts as manual once we have sized it ourselves.
        if (expected === null) {
          void persist();
          return;
        }
        try {
          // The payload is PHYSICAL pixels while the size we asked for was
          // LOGICAL: on any display that is not at 100% scaling a naive
          // comparison reads every auto-fit as a manual resize.
          const scale = await win.scaleFactor();
          if (Math.abs(payload.height / scale - expected) <= 4) {
            void persist();
            return;
          }
        } catch {
          // Fall through: an unreadable scale means we cannot tell, and
          // fighting the player for control of the window is the worse error.
        }
        setManualSize(true);
        void persist();
      })();
    });
    return () => {
      void unlistenMove.then((f) => f());
      void unlistenResize.then((f) => f());
    };
  }, [native, modId]);

  // Click-through makes the window ignore the mouse entirely, so it cannot be
  // switched off from here — the main window emits this event to hand input
  // back. Without that escape hatch, enabling it would strand the overlay.
  useEffect(() => {
    if (!native) return;
    const unlisten = listen(OVERLAY_INTERACTIVE_EVENT, () => {
      void getCurrentWindow().setIgnoreCursorEvents(false);
      setClickThrough(false);
    });
    return () => {
      void unlisten.then((f) => f());
    };
  }, [native]);

  // Fit the window to its contents. A four-row board in a window sized for
  // eight is mostly empty pane hanging over the game; the HUD should be as
  // tall as it needs to be and no taller.
  const rowCount = record?.rows?.length ?? 0;
  useEffect(() => {
    if (!native || manualSize || !body.current) return;
    const chrome = compact ? 26 : 46; // header (+ footer)
    // Measured content, floored by the row count: `scrollHeight` is a frame
    // behind on the render that adds a row, and a HUD that lags one player
    // behind the fight looks broken.
    const measured = body.current.scrollHeight;
    const wanted = Math.round(Math.max(measured, rowCount * 24 + 8) + chrome);
    const clamped = Math.max(72, Math.min(600, wanted));
    if (autoHeight.current !== null && Math.abs(autoHeight.current - clamped) < 4) return;
    autoHeight.current = clamped;
    const win = getCurrentWindow();
    void (async () => {
      try {
        const size = await win.outerSize();
        const scale = await win.scaleFactor();
        await win.setSize(new LogicalSize(Math.round(size.width / scale), clamped));
      } catch {
        // A window that will not resize is not a reason to stop drawing.
      }
    })();
  }, [native, manualSize, compact, rowCount]);

  const toggleClickThrough = async () => {
    if (!native) return;
    const next = !clickThrough;
    await getCurrentWindow().setIgnoreCursorEvents(next);
    setClickThrough(next);
    void emit('rsmm://overlay-clickthrough', { modId, enabled: next });
  };

  const columns = record?.columns ?? [];
  const rows = record?.rows ?? [];
  const highlight = record?.highlight ?? null;
  const stale =
    !record?.exists || (record.updated > 0 && Date.now() / 1000 - record.updated > STALE_AFTER_S);

  // Rank changes flash, so a takeover is visible without staring at numbers.
  const rowKey = (row: Record<string, string | number | boolean>, i: number) =>
    String(row[columns[0]?.key ?? ''] ?? i);
  const moved: Record<string, boolean> = {};
  rows.forEach((row, i) => {
    const key = rowKey(row, i);
    moved[key] = prevOrder.current[key] !== undefined && prevOrder.current[key] !== i;
  });
  prevOrder.current = Object.fromEntries(rows.map((row, i) => [rowKey(row, i), i]));

  const Icon = ICONS[(record?.icon ?? 'list') as keyof typeof ICONS] ?? List;

  // The card is sized by its CONTENT (max-h-screen, not h-screen). If the
  // window is taller than the board — before auto-fit runs, or when the player
  // has sized it by hand — the surplus stays transparent instead of rendering
  // as an empty slab of card over the game.
  return (
    <div
      className={`relative flex max-h-screen w-screen flex-col overflow-hidden rounded-md border border-crimson/40 bg-pitch/85 text-parchment shadow-lg backdrop-blur-sm ${
        stale ? 'opacity-70' : ''
      }`}
    >
      <header
        data-tauri-drag-region
        className="flex shrink-0 cursor-move items-center gap-2 border-b border-border/70 px-2 py-1"
      >
        <Icon className="pointer-events-none h-3.5 w-3.5 text-crimson" />
        <span
          data-tauri-drag-region
          className="font-mono pointer-events-none text-[0.6rem] uppercase tracking-[0.2em] text-ash"
        >
          rsmm
        </span>
        <span
          data-tauri-drag-region
          className="font-fraktur pointer-events-none flex-1 truncate text-sm text-parchment"
          title={record?.modName ?? modId}
        >
          {record?.title ?? modId}
        </span>
        <button
          type="button"
          onClick={() => setCompact((c) => !c)}
          title={compact ? t('Show details') : t('Compact')}
          className="text-ash transition-colors hover:text-parchment"
        >
          {compact ? <Maximize2 className="h-3 w-3" /> : <Minimize2 className="h-3 w-3" />}
        </button>
        <button
          type="button"
          onClick={() => void toggleClickThrough()}
          title={
            clickThrough
              ? t('Click-through on — press Ctrl+Alt+O (or use Settings) to undo')
              : t('Let clicks pass through to the game')
          }
          className={`transition-colors hover:text-parchment ${
            clickThrough ? 'text-gilt' : 'text-ash'
          }`}
        >
          {clickThrough ? <Pin className="h-3 w-3" /> : <MousePointerClick className="h-3 w-3" />}
        </button>
        <button
          type="button"
          onClick={() => native && void getCurrentWindow().close()}
          title={t('Close overlay')}
          className="text-ash transition-colors hover:text-crimson"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </header>

      <div ref={body} className="min-h-0 flex-1 overflow-y-auto">
        {record?.error ? (
          <p className="px-3 py-4 text-center text-xs text-crimson">{record.error}</p>
        ) : rows.length > 0 ? (
          <ul className="py-1">
            {rows.map((row, i) => {
              const key = rowKey(row, i);
              const isHighlighted = Boolean(highlight && row[highlight]);
              return (
                <li
                  key={key}
                  className={[
                    'flex items-center gap-1.5 px-2 py-1',
                    isHighlighted
                      ? 'border-l-2 border-gilt bg-oxblood/20 text-parchment'
                      : 'border-l-2 border-transparent text-smoke',
                    moved[key] ? 'animate-ink-stamp' : '',
                  ].join(' ')}
                >
                  <span className="font-mono w-3 shrink-0 text-right text-[0.7rem] text-ash">
                    {i + 1}
                  </span>
                  {columns.map((col) => (
                    <Cell key={col.key} column={col} value={row[col.key]} />
                  ))}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="px-3 py-4 text-center text-xs text-ash">
            {/* `record.empty` is the MOD's own copy — shown as published. */}
            {error ??
              (record?.source === 'library'
                ? t('This mod is not applied yet — run Apply, then start the game.')
                : (record?.empty ?? t('No data yet.')))}
          </p>
        )}
      </div>

      {/* Undecorated windows get no OS resize border, so the HUD grows its
          own: drag the corner. `startResizeDragging` hands the drag to the
          window manager, which is what makes it feel native. */}
      {native && (
        <button
          type="button"
          title={t('Drag to resize')}
          onMouseDown={(e) => {
            e.preventDefault();
            setManualSize(true);
            void getCurrentWindow().startResizeDragging('SouthEast');
          }}
          className="absolute bottom-0 right-0 cursor-nwse-resize p-0.5 text-char transition-colors hover:text-parchment"
        >
          <GripHorizontal className="h-3 w-3 rotate-45" />
        </button>
      )}

      {!compact && (
        <footer className="flex shrink-0 items-center gap-2 border-t border-border/70 px-2 py-1 text-[0.68rem] text-ash">
          {/* Footer values are whatever the mod published — key + value, in
              its own words, separated so two pairs never read as one. */}
          {Object.entries(record?.meta ?? {})
            .slice(0, 3)
            .map(([k, v], i) => (
              <span key={k} className="font-mono truncate">
                {i > 0 ? <span className="text-char"> · </span> : null}
                {typeof v === 'number' ? `${compactNumber(v)} ${k}` : `${k} ${v}`}
              </span>
            ))}
          <span className="flex-1" />
          {clickThrough ? <span className="text-gilt">ctrl+alt+O</span> : null}
          <span>{stale ? t('idle') : t('live')}</span>
        </footer>
      )}
    </div>
  );
}

export default OverlayHud;
