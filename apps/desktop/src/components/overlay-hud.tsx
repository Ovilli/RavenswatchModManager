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
import { Maximize2, Minimize2, MousePointerClick, Pin, RotateCcw, X } from 'lucide-react';
import { GripHorizontal } from 'lucide-react';
import {
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useT } from '../lib/i18n-react';
import { gridTracks, readOverlayLive } from '../lib/overlay-state';
import { overlayTransparent, resetOverlayWindow, savePosition } from '../lib/overlay-windows';
import {
  type ModConfigValue,
  type OverlayColumn,
  type OverlayControl,
  type OverlayRecord,
  listOverlays,
  readOverlayState,
  setModConfig,
} from '../lib/rsmm';
import { attachSmoothWheel } from '../lib/smooth-scroll';

/** How often the data is re-read. Mods publish at their own cadence. */
const POLL_MS = 1000;
/** A publish older than this means nothing is playing right now. */
const STALE_AFTER_S = 20;

/** Event the main window emits to hand input back after click-through. */
export const OVERLAY_INTERACTIVE_EVENT = 'rsmm://overlay-interactive';

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

/**
 * `?demo=list`: the other shape a board takes — rows in the mod's own order
 * (no sort, so no rank numbers), several text columns, a highlighted row.
 * Deliberately generic copy: the client never carries one mod's UI.
 */
const DEMO_LIST: OverlayRecord = {
  ...DEMO,
  title: 'Objectives',
  icon: 'trophy',
  columns: [
    { key: 'task', label: 'Objective', type: 'text', format: 'plain', suffix: '' },
    { key: 'progress', label: 'Progress', type: 'bar', format: 'plain', suffix: '' },
    { key: 'count', label: '', type: 'text', format: 'plain', suffix: '' },
    { key: 'time', label: 'Time', type: 'text', format: 'plain', suffix: '' },
    { key: 'reward', label: 'Reward', type: 'text', format: 'plain', suffix: '' },
  ],
  sort: null,
  highlight: 'done',
  rows: [
    {
      task: 'Defeat 20 enemies',
      progress: 0.65,
      count: '13/20',
      time: '1:12',
      reward: '40 shards',
      done: false,
    },
    { task: 'Open 2 chests', progress: 1, count: '', time: '', reward: 'Paid', done: true },
    {
      task: 'Win without a hit',
      progress: 0.2,
      count: '2/10',
      time: '3:41',
      reward: '60 shards + 1 reroll',
      done: false,
    },
  ],
  meta: { completed: 4, streak: 1 },
};

function compactNumber(n: number): string {
  if (!Number.isFinite(n)) return '0';
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}m`;
  if (Math.abs(n) >= 10_000) return `${(n / 1000).toFixed(0)}k`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return n.toFixed(0);
}

/** Numbers and percents read right-aligned, under a right-aligned header. */
const RIGHT_ALIGNED = new Set<OverlayColumn['type']>(['number', 'percent']);

// `.font-mono` is the app's LABEL style (upper-cased, tracked out). A value is
// content, not a label: without the reset a mod's "/s" suffix rendered "/S"
// and the meta footer shouted "84K TOTAL".
const MONO_VALUE = 'font-mono normal-case tracking-normal';

function Cell({
  column,
  value,
  primary,
  highlighted,
}: {
  column: OverlayColumn;
  value: string | number | boolean | undefined;
  /** The board's first text column: full size, everything else is secondary. */
  primary: boolean;
  highlighted: boolean;
}) {
  if (value === undefined || value === null || value === '') return <span />;

  if (column.type === 'bar') {
    const pct = Math.max(0, Math.min(1, Number(value) || 0));
    return (
      <span className="relative h-1.5 w-full overflow-hidden rounded-sm bg-char/40">
        <span
          className={`absolute inset-y-0 left-0 transition-[width] duration-500 ease-grimoire ${
            highlighted ? 'bg-gilt' : 'bg-crimson'
          }`}
          style={{ width: `${pct * 100}%` }}
        />
      </span>
    );
  }
  if (column.type === 'text') {
    return (
      <span
        className={primary ? 'min-w-0 truncate text-sm' : 'min-w-0 truncate text-xs'}
        title={String(value)}
      >
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
  return (
    <span className={`${MONO_VALUE} whitespace-nowrap text-right text-xs tabular-nums`}>
      {text}
    </span>
  );
}

/** Slider steps for a float control: fine enough to feel continuous. */
const FLOAT_STEPS = 100;

/**
 * One live control: a field of the mod's own config schema, drawn by type.
 * The label and range are the MOD's (from its schema), shown as declared.
 */
function ControlRow({
  control,
  value,
  onChange,
}: {
  control: OverlayControl;
  value: ModConfigValue;
  onChange: (v: ModConfigValue) => void;
}) {
  if (control.type === 'bool') {
    return (
      <label className="flex items-center gap-2 px-2 py-1 text-xs text-smoke">
        <span className="flex-1 truncate">{control.label}</span>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
          className="accent-crimson"
        />
      </label>
    );
  }
  if (control.type === 'enum') {
    return (
      <label className="flex items-center gap-2 px-2 py-1 text-xs text-smoke">
        <span className="flex-1 truncate">{control.label}</span>
        <select
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          className="max-w-[9rem] rounded-sm border border-border bg-pitch px-1 py-0.5 text-parchment"
        >
          {control.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
    );
  }
  const min = control.min ?? 0;
  const max = control.max ?? 1;
  const step = control.type === 'int' ? 1 : (max - min) / FLOAT_STEPS;
  const num = Number(value ?? min);
  return (
    <label className="flex items-center gap-2 px-2 py-1 text-xs text-smoke">
      <span className="w-20 shrink-0 truncate" title={control.label}>
        {control.label}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={num}
        onChange={(e) => {
          const v = Number(e.target.value);
          onChange(control.type === 'int' ? Math.round(v) : v);
        }}
        className="min-w-0 flex-1 accent-crimson"
      />
      <span className="font-mono w-10 shrink-0 text-right text-xs tabular-nums text-parchment">
        {control.type === 'int' ? num.toFixed(0) : num.toFixed(Math.abs(max - min) >= 10 ? 0 : 2)}
      </span>
    </label>
  );
}

export function OverlayHud({ modId }: { modId: string }) {
  const t = useT();
  const [record, setRecord] = useState<OverlayRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compact, setCompact] = useState(false);
  const [clickThrough, setClickThrough] = useState(false);
  const inFlight = useRef(false);
  // The last live payload rendered, to skip identical re-renders.
  const lastLive = useRef<string | null>(null);
  // The declaration, cached for the session. Null means "ask the CLI on the
  // next tick" — the state of affairs on mount and after a live read failed.
  const declared = useRef<OverlayRecord | null>(null);
  const prevOrder = useRef<Record<string, number>>({});
  const prevLit = useRef<Record<string, boolean>>({});
  const body = useRef<HTMLDivElement | null>(null);
  // The card, and the body's content at its natural height (the body itself
  // is a scroll box, so its own height says nothing about what it holds).
  const card = useRef<HTMLDivElement | null>(null);
  const content = useRef<HTMLDivElement | null>(null);
  // Control values as the player set them. Seeded from the declaration and
  // then owned here: the CLI reports the saved value only when re-asked, and a
  // slider that snapped back between writes would fight the drag.
  const [controlValues, setControlValues] = useState<Record<string, ModConfigValue>>({});
  // The same values, readable synchronously: a change is computed from here
  // and queued for writing in the same tick. Computing it inside a state
  // updater did not work — React runs updaters later, at render, so the flush
  // that followed found nothing queued and every write carried the PREVIOUS
  // value (the camera trailed the slider by one move).
  const controlValuesRef = useRef<Record<string, ModConfigValue>>({});
  const pendingWrite = useRef<Record<string, ModConfigValue> | null>(null);
  const writing = useRef(false);
  const [controlError, setControlError] = useState<string | null>(null);
  const demoParam = new URLSearchParams(window.location.search).get('demo');
  const demo = demoParam === '1' || demoParam === 'list';
  // Outside the Tauri shell there is no window to drive and no sidecar to
  // call; the component still renders so the design can be previewed.
  const native = isTauri();

  // The window paints its own card; the app's page background would otherwise
  // fill the frame and defeat `transparent: true`. Where the window is opaque
  // (Linux, see openOverlay) the page background stays: clearing it would
  // leave the area around the card undefined.
  useEffect(() => {
    if (!overlayTransparent()) {
      document.body.style.overflow = 'hidden';
      return;
    }
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

  /**
   * Re-read the DECLARATION through the CLI.
   *
   * Expensive — it spawns the bundled Python and walks every installed mod's
   * manifest — so it runs on mount and then only when the live read tells us
   * the picture has changed (the mod was uninstalled, renamed, or has only
   * just been applied). It used to run once a second, per open overlay, while
   * the game was being played.
   */
  const loadDeclaration = useCallback(async () => {
    if (!native) return null;
    const list = await listOverlays();
    const found = list?.overlays.find((o) => o.modId === modId) ?? null;
    setRecord(found);
    setError(found ? null : `no installed mod "${modId}" declares an overlay`);
    return found;
  }, [native, modId]);

  // Seed control values from the declaration the first time it arrives.
  const declaredControls = record?.controls;
  const controls = declaredControls ?? [];
  useEffect(() => {
    if (!declaredControls?.length || Object.keys(controlValuesRef.current).length > 0) return;
    const seeded = Object.fromEntries(declaredControls.map((c) => [c.key, c.value]));
    controlValuesRef.current = seeded;
    setControlValues(seeded);
  }, [declaredControls]);

  /**
   * Write control values to the mod's config, live. Each write spawns the
   * CLI, so writes are COALESCED: one in flight at a time, and whatever the
   * player did meanwhile goes out as one write when it lands. A drag across a
   * slider is then two or three writes, not one per pixel.
   */
  const flushControls = useCallback(async () => {
    if (writing.current || !pendingWrite.current || !native) return;
    writing.current = true;
    const values = pendingWrite.current;
    pendingWrite.current = null;
    try {
      const res = await setModConfig(modId, values, { live: true, merge: true });
      setControlError(res.ok === false ? (res.error ?? 'config write failed') : null);
    } catch (e) {
      setControlError(e instanceof Error ? e.message : String(e));
    } finally {
      writing.current = false;
      if (pendingWrite.current) void flushControls();
    }
  }, [modId, native]);

  const changeControl = useCallback(
    (key: string, value: ModConfigValue) => {
      const next = { ...controlValuesRef.current, [key]: value };
      controlValuesRef.current = next;
      // Every control's value, written with `merge` so the mod's fields that
      // are NOT controls keep theirs.
      pendingWrite.current = next;
      setControlValues(next);
      void flushControls();
    },
    [flushControls],
  );

  const poll = useCallback(async () => {
    if (demo) {
      setRecord(demoParam === 'list' ? DEMO_LIST : DEMO);
      return;
    }
    if (!native || inFlight.current) return;
    inFlight.current = true;
    try {
      // No declaration yet (first tick, or the mod was not installed last
      // time we looked): that is the one case worth paying for the CLI.
      const declaration = declared.current ?? (await loadDeclaration());
      declared.current = declaration;
      if (!declaration?.statePath) return;
      // A controls-only overlay publishes no rows: nothing to follow.
      if (!declaration.columns?.length) return;

      const state = await readOverlayState(declaration.statePath);
      const live = state.exists
        ? readOverlayLive(state.content, declaration.sort ?? null)
        : { rows: [], meta: {}, updated: 0, exists: false };
      // Re-render only when something changed. A new record every second
      // repainted the window every second whether or not a number moved, and
      // each repaint is a chance for an X11 webview to blank out.
      const sig = JSON.stringify(live);
      if (sig === lastLive.current) return;
      lastLive.current = sig;
      setRecord((cur) => (cur ? { ...cur, ...live } : { ...declaration, ...live }));
      setError(null);
    } catch (e) {
      // The state file went away or became unreadable — most likely the mod
      // was uninstalled or re-applied under the player's feet. Drop the cached
      // declaration so the next tick re-asks the CLI and can report that
      // properly, rather than showing a stale HUD or going blank.
      declared.current = null;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
    }
  }, [demo, demoParam, native, loadDeclaration]);

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
    // Width is the player's; height is not (see the fit below), so a resize
    // only needs remembering.
    const unlistenResize = win.onResized(() => void persist());
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

  // Fit the window to the card, exactly. The window used to be sized from
  // guesses (header+footer "46px", "24px per row") that drifted with every
  // style change — the card then ended above the window's bottom and, where
  // the window is opaque (Linux), left a dark slab under the HUD. It also only
  // re-measured when the ROW COUNT changed. Now the real heights are observed:
  // natural height = the card minus its scroll box plus what the box holds.
  //
  // Height ALWAYS follows the content; only the width is the player's. When
  // a hand-resize switched fitting off, a window dragged taller than the card
  // kept the surplus, which on Linux (opaque window) is a grey box hanging
  // off the HUD. The grip now drags width only, and a height change from
  // anywhere else (a window-manager edge, a snap) settles back once the
  // resizing stops.
  useEffect(() => {
    if (!native || !card.current || !body.current || !content.current) return;
    const cardEl = card.current;
    const bodyEl = body.current;
    const contentEl = content.current;
    const win = getCurrentWindow();
    let frame = 0;
    const fit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const natural = cardEl.offsetHeight - bodyEl.clientHeight + contentEl.offsetHeight;
        const wanted = Math.max(40, Math.min(600, Math.ceil(natural)));
        // Against the window's real height, not the last size we asked for:
        // a window someone else resized must be caught too.
        if (Math.abs(window.innerHeight - wanted) < 2) return;
        void (async () => {
          try {
            const size = await win.outerSize();
            const scale = await win.scaleFactor();
            await win.setSize(new LogicalSize(Math.round(size.width / scale), wanted));
          } catch {
            // A window that will not resize is not a reason to stop drawing.
          }
        })();
      });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(cardEl);
    observer.observe(contentEl);
    // Settle a window resized from outside once the drag stops — snapping
    // back on every frame of a drag would fight the window manager.
    let settle = 0;
    const onWindowResize = () => {
      window.clearTimeout(settle);
      settle = window.setTimeout(fit, 200);
    };
    window.addEventListener('resize', onWindowResize);
    fit();
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(settle);
      window.removeEventListener('resize', onWindowResize);
      observer.disconnect();
    };
  }, [native]);

  // An overlay that comes up maximized (saved that way before maximizing was
  // switched off) un-maximizes itself: there is no title bar to do it with.
  useEffect(() => {
    if (!native) return;
    const win = getCurrentWindow();
    void win
      .isMaximized()
      .then((max) => (max ? win.unmaximize() : undefined))
      .catch(() => undefined);
  }, [native]);

  // Back to a fresh window: default width, centred (height re-fits itself).
  const resetWindow = async () => {
    if (!native) return;
    await resetOverlayWindow(modId, getCurrentWindow());
  };

  // Drag from the title bar. Not `data-tauri-drag-region`: a DOUBLE-click on
  // one maximizes the window, which is how an overlay ended up full-screen
  // and stuck there. A plain mousedown drag has no double-click behaviour.
  const dragFromHeader = (e: ReactMouseEvent) => {
    if (!native || e.button !== 0 || e.detail > 1) return;
    if ((e.target as HTMLElement).closest('button')) return;
    void getCurrentWindow().startDragging();
  };

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
  const controlsOnly = columns.length === 0 && controls.length > 0;
  const stale =
    !controlsOnly &&
    (!record?.exists || (record.updated > 0 && Date.now() / 1000 - record.updated > STALE_AFTER_S));

  // A rank number only means something on a board the mod SORTS. On a list in
  // the mod's own order (objectives, a checklist) "1 2 3" reads as a ranking
  // that is not there.
  const ranked = Boolean(record?.sort?.key);

  // A row that changed state stamps, so it is seen without staring at
  // numbers: on a ranked board, a row that moved (a takeover); on any board, a
  // row that just became highlighted, or a row that is new since the last
  // publish (but not on the first paint, where everything is new).
  const rowKey = (row: Record<string, string | number | boolean>, i: number) =>
    String(row[columns[0]?.key ?? ''] ?? i);
  const firstPaint = Object.keys(prevOrder.current).length === 0;
  const stamped: Record<string, boolean> = {};
  rows.forEach((row, i) => {
    const key = rowKey(row, i);
    const before = prevOrder.current[key];
    const lit = Boolean(highlight && row[highlight]);
    stamped[key] =
      (ranked && before !== undefined && before !== i) ||
      (!firstPaint && before === undefined) ||
      (lit && prevLit.current[key] === false);
  });
  prevOrder.current = Object.fromEntries(rows.map((row, i) => [rowKey(row, i), i]));
  prevLit.current = Object.fromEntries(
    rows.map((row, i) => [rowKey(row, i), Boolean(highlight && row[highlight])]),
  );
  const tracks = gridTracks(columns, ranked);
  const showHeader = !compact && columns.some((c) => c.label.trim() !== '');
  const firstTextKey = columns.find((c) => c.type === 'text')?.key;

  // The card is sized by its CONTENT (max-h-screen, not h-screen). If the
  // window is taller than the board — before auto-fit runs, or when the player
  // has sized it by hand — the surplus stays transparent instead of rendering
  // as an empty slab of card over the game.
  return (
    <div
      ref={card}
      className={`group relative flex max-h-screen w-screen flex-col overflow-hidden rounded-md border border-crimson/40 bg-pitch/85 text-parchment shadow-lg backdrop-blur-sm ${
        stale ? 'opacity-70' : ''
      }`}
    >
      <header
        onMouseDown={dragFromHeader}
        className="flex shrink-0 cursor-move items-center gap-1 border-b border-border/70 py-1 pl-2.5 pr-1"
      >
        {/* The title alone. A wordmark and a 14px glyph beside it were chrome
            competing with the one word that says what this board is. */}
        <span
          className="font-fraktur pointer-events-none flex-1 truncate text-base leading-tight text-parchment"
          title={record?.modName ?? modId}
        >
          {record?.title ?? modId}
        </span>
        {/* Window buttons are used a few times a session and read over the
            game the whole time, so they only show while the mouse is on the
            card. Click-through is the exception: then the card cannot be
            hovered, so its pin stays visible as the reminder of how to undo. */}
        <div
          className={`flex items-center transition-opacity duration-150 ${
            clickThrough
              ? 'opacity-100'
              : 'opacity-0 group-hover:opacity-100 focus-within:opacity-100'
          }`}
        >
          {!clickThrough && (
            <button
              type="button"
              onClick={() => void resetWindow()}
              title={t('Reset size and position')}
              className="rounded-sm p-1 text-ash transition-colors hover:bg-char/40 hover:text-parchment"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          )}
          {!clickThrough && (
            <button
              type="button"
              onClick={() => setCompact((c) => !c)}
              title={compact ? t('Show details') : t('Compact')}
              className="rounded-sm p-1 text-ash transition-colors hover:bg-char/40 hover:text-parchment"
            >
              {compact ? (
                <Maximize2 className="h-3.5 w-3.5" />
              ) : (
                <Minimize2 className="h-3.5 w-3.5" />
              )}
            </button>
          )}
          <button
            type="button"
            onClick={() => void toggleClickThrough()}
            title={
              clickThrough
                ? t('Click-through on — press Ctrl+Alt+O (or use Settings) to undo')
                : t('Let clicks pass through to the game')
            }
            className={`rounded-sm p-1 transition-colors hover:bg-char/40 hover:text-parchment ${
              clickThrough ? 'text-gilt' : 'text-ash'
            }`}
          >
            {clickThrough ? (
              <Pin className="h-3.5 w-3.5" />
            ) : (
              <MousePointerClick className="h-3.5 w-3.5" />
            )}
          </button>
          {!clickThrough && (
            <button
              type="button"
              onClick={() => native && void getCurrentWindow().close()}
              title={t('Close overlay')}
              className="rounded-sm p-1 text-ash transition-colors hover:bg-char/40 hover:text-crimson"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </header>

      <div ref={body} className="min-h-0 flex-1 overflow-y-auto">
        <div ref={content}>
          {!record?.error && controls.length > 0 && (
            <div className={`py-1 ${columns.length > 0 ? 'border-b border-border/70' : ''}`}>
              {controls.map((c) => (
                <ControlRow
                  key={c.key}
                  control={c}
                  value={controlValues[c.key] ?? c.value}
                  onChange={(v) => changeControl(c.key, v)}
                />
              ))}
              {controlError ? (
                <p className="px-2 pb-1 text-xs text-crimson">{controlError}</p>
              ) : null}
            </div>
          )}
          {record?.error ? (
            <p className="px-3 py-4 text-center text-xs text-crimson">{record.error}</p>
          ) : controlsOnly ? null : rows.length > 0 ? (
            <ul className="grid gap-x-2 py-1" style={{ gridTemplateColumns: tracks }}>
              {showHeader && (
                // Column labels are the MOD's own copy, shown as declared.
                <li className="col-span-full grid grid-cols-subgrid items-end border-l-2 border-transparent px-2 pb-0.5 text-[0.65rem] uppercase tracking-[0.12em] text-ash">
                  {ranked ? <span /> : null}
                  {columns.map((col) => (
                    <span
                      key={col.key}
                      className={`truncate ${RIGHT_ALIGNED.has(col.type) ? 'text-right' : ''}`}
                    >
                      {col.label}
                    </span>
                  ))}
                </li>
              )}
              {rows.map((row, i) => {
                const key = rowKey(row, i);
                const isHighlighted = Boolean(highlight && row[highlight]);
                return (
                  <li
                    key={key}
                    className={[
                      'col-span-full grid grid-cols-subgrid items-center px-2 py-1',
                      isHighlighted
                        ? 'border-l-2 border-gilt bg-oxblood/20 text-parchment'
                        : 'border-l-2 border-transparent text-smoke',
                      stamped[key] ? 'animate-ink-stamp' : '',
                    ].join(' ')}
                  >
                    {ranked ? (
                      <span className={`${MONO_VALUE} text-right text-xs text-ash`}>{i + 1}</span>
                    ) : null}
                    {columns.map((col) => (
                      <Cell
                        key={col.key}
                        column={col}
                        value={row[col.key]}
                        primary={col.key === firstTextKey}
                        highlighted={isHighlighted}
                      />
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
      </div>

      {/* Undecorated windows get no OS resize border, so the HUD grows its
          own: drag the corner. `startResizeDragging` hands the drag to the
          window manager, which is what makes it feel native. WIDTH only
          ('East'): the height is the content's, see the fit above. */}
      {native && (
        <button
          type="button"
          title={t('Drag to resize')}
          onMouseDown={(e) => {
            e.preventDefault();
            void getCurrentWindow().startResizeDragging('East');
          }}
          className="absolute bottom-0 right-0 cursor-ew-resize p-0.5 text-char transition-colors hover:text-parchment"
        >
          <GripHorizontal className="h-3 w-3 rotate-90" />
        </button>
      )}

      {!compact && (
        <footer className="flex shrink-0 items-center gap-2 border-t border-border/70 px-2 py-1 text-xs text-ash">
          {/* Footer values are whatever the mod published — key + value, in
              its own words, separated so two pairs never read as one. */}
          {Object.entries(record?.meta ?? {})
            .slice(0, 3)
            .map(([k, v], i) => (
              <span key={k} className={`${MONO_VALUE} truncate`}>
                {i > 0 ? <span className="text-char"> · </span> : null}
                {typeof v === 'number' ? `${compactNumber(v)} ${k}` : `${k} ${v}`}
              </span>
            ))}
          <span className="flex-1" />
          {clickThrough ? <span className="text-gilt">ctrl+alt+O</span> : null}
          {/* Only the exception is worth words: "live" on every frame was noise. */}
          {stale ? <span>{t('idle')}</span> : null}
        </footer>
      )}
    </div>
  );
}

export default OverlayHud;
