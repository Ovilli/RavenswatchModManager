'use client';

import { useId, useRef, useState } from 'react';

const nf = new Intl.NumberFormat();
const dayFmt = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
});
const axisFmt = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });

// `day` is a calendar date (YYYY-MM-DD); parse it as local noon so a negative
// UTC offset never shows the previous day.
const asDate = (day: string) => new Date(`${day}T12:00:00`);

/** Round a maximum up to a readable gridline value (1, 2, 5 × 10ⁿ). */
function niceMax(n: number): number {
  if (n <= 4) return Math.max(n, 1);
  const p = 10 ** Math.floor(Math.log10(n));
  const m = n / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

/**
 * One daily series as an area chart with a hover layer: a crosshair snaps to
 * the nearest day and a readout shows that day's value. Arrow keys move it when
 * the chart has focus. A visually hidden table carries every value for screen
 * readers, so nothing is reachable by hover alone.
 */
export function TrendChart({
  label,
  data,
  dimmed = false,
  tall = false,
}: {
  label: string;
  data: { day: string; n: number }[];
  /** Hold the previous render faded while a new period loads. */
  dimmed?: boolean;
  tall?: boolean;
}) {
  const id = useId();
  const box = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  const total = data.reduce((s, d) => s + d.n, 0);
  const peak = Math.max(0, ...data.map((d) => d.n));
  const top = niceMax(peak);
  const W = 600;
  const H = 200;
  const plotHeight = tall ? 180 : 120;
  const n = data.length;
  const x = (i: number) => (n > 1 ? (i / (n - 1)) * W : W / 2);
  const y = (v: number) => H - (v / top) * (H - 8) - 1;
  const line = data.map((d, i) => `${x(i).toFixed(1)},${y(d.n).toFixed(1)}`).join(' ');
  const area = `0,${H} ${line} ${W},${H}`;

  const pick = (clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (!r || n === 0) return;
    const f = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    setHover(Math.round(f * (n - 1)));
  };
  const point = hover != null ? data[hover] : undefined;
  const tipLeft = hover != null ? (x(hover) / W) * 100 : 0;

  return (
    <figure className={`grimoire-card p-4 transition-opacity ${dimmed ? 'opacity-50' : ''}`}>
      <figcaption className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="text-right">
          <span className="font-display text-2xl tabular-nums text-parchment">
            {nf.format(total)}
          </span>
          {n ? (
            <span className="ml-2 text-xs text-muted-foreground">
              {nf.format(Math.round((total / n) * 10) / 10)}/day
            </span>
          ) : null}
        </span>
      </figcaption>

      <div className="mt-4 flex gap-2">
        {/* y-axis: the gridline values, recessive */}
        <div
          className="-my-1.5 flex flex-col justify-between text-right text-[0.7rem] tabular-nums text-muted-foreground"
          style={{ height: plotHeight + 12 }}
          aria-hidden
        >
          <span>{nf.format(top)}</span>
          <span>{nf.format(top / 2)}</span>
          <span>0</span>
        </div>

        <div
          ref={box}
          className="relative flex-1 cursor-crosshair touch-none rounded outline-none focus-visible:ring-2 focus-visible:ring-ring"
          style={{ height: plotHeight }}
          // biome-ignore lint/a11y/noNoninteractiveTabindex: keyboard users explore the chart with the arrow keys.
          tabIndex={0}
          role="img"
          aria-label={`${label}: ${nf.format(total)} over ${n} days, peak ${nf.format(peak)} in a day. Arrow keys read single days.`}
          onPointerMove={(e) => pick(e.clientX)}
          onPointerDown={(e) => pick(e.clientX)}
          onPointerLeave={() => setHover(null)}
          onFocus={() => setHover((h) => h ?? n - 1)}
          onBlur={() => setHover(null)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? n - 1) - 1));
            else if (e.key === 'ArrowRight') setHover((h) => Math.min(n - 1, (h ?? 0) + 1));
            else return;
            e.preventDefault();
          }}
        >
          <svg
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            className="h-full w-full overflow-visible text-crimson"
            aria-hidden="true"
            focusable="false"
          >
            <defs>
              <linearGradient id={`fill-${id}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="currentColor" stopOpacity={0.3} />
                <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
              </linearGradient>
            </defs>
            {[0, 0.5, 1].map((f) => (
              <line
                key={f}
                x1={0}
                x2={W}
                y1={y(top * f)}
                y2={y(top * f)}
                className="stroke-border"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
            ))}
            <polygon points={area} fill={`url(#fill-${id})`} />
            <polyline
              points={line}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
            {hover != null && point ? (
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={0}
                y2={H}
                stroke="hsl(var(--parchment) / 0.45)"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </svg>

          {hover != null && point ? (
            <>
              {/* HTML, not SVG, so the marker stays round under the stretched viewBox. */}
              <span
                className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-card"
                style={{
                  left: `${tipLeft}%`,
                  top: `${(y(point.n) / H) * 100}%`,
                  background: 'hsl(var(--crimson-text))',
                }}
              />
              <div
                className="pointer-events-none absolute -top-2 z-10 whitespace-nowrap rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-lg"
                style={{
                  left: `${tipLeft}%`,
                  transform: `translate(${tipLeft > 70 ? '-100%' : tipLeft < 30 ? '0' : '-50%'}, -100%)`,
                }}
              >
                <div className="font-semibold tabular-nums text-parchment">
                  {nf.format(point.n)}
                </div>
                <div className="text-muted-foreground">{dayFmt.format(asDate(point.day))}</div>
              </div>
            </>
          ) : null}
        </div>
      </div>

      {n > 1 ? (
        <div
          className="mt-2 flex justify-between pl-8 text-[0.7rem] text-muted-foreground"
          aria-hidden
        >
          <span>{axisFmt.format(asDate(data[0]?.day ?? ''))}</span>
          <span>{axisFmt.format(asDate(data[n - 1]?.day ?? ''))}</span>
        </div>
      ) : null}

      <table className="sr-only">
        <caption>{label} per day</caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col">{label}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.day}>
              <td>{d.day}</td>
              <td>{d.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
