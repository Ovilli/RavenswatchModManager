/**
 * Renderer for the generic `item-grid` config field.
 *
 * Everything that makes one grid differ from another comes from the mod: the
 * sections, their labels and filters, the per-item number, the title and quote
 * copy, the layout, and an optional theme of game textures (decoded from the
 * player's install by the CLI, never shipped) with the ink that reads on each.
 * With no theme it draws in the app's own style. This component must never
 * learn what a particular grid is for.
 *
 * Layout follows the space the grid is GIVEN, measured, not the window size:
 * the same grid sits in a wide dialog, in the library's config view, and under
 * any UI scale, and a viewport breakpoint guessed wrong in all three. Columns
 * share that space and never overflow it.
 */
import { Input } from '@rsmm/ui';
import { type CSSProperties, Fragment, useEffect, useRef, useState } from 'react';
import { useT } from '../lib/i18n-react';
import {
  candidates,
  groupSections,
  minItems,
  numberEditable,
  optionNumber,
  sectionCount,
  sectionItems,
  withCount,
  withItems,
  withNumber,
  withSectionReset,
} from '../lib/item-grid';
import type { ItemGridSection, ItemGridSpec, ItemGridValue, ModConfigChoice } from '../lib/rsmm';

type Theme = Record<string, string>;

/** Room (in CSS px) each column needs before columns are worth using. */
const COLUMN_MIN_PX = 240;
/** Extra room needed before the portrait/quote aside sits beside the columns. */
const ASIDE_PX = 220;

/** A stretched theme texture. Only inline data URLs ever arrive here. */
const skin = (url: string | undefined): CSSProperties =>
  url ? { backgroundImage: `url("${url}")`, backgroundSize: '100% 100%' } : {};

/** The 9-sliced frame a `panel` texture draws around a block. */
const frame = (url: string | undefined): CSSProperties | undefined =>
  url
    ? {
        borderStyle: 'solid',
        borderWidth: '12px',
        borderImage: `url("${url}") 22 fill / 12px stretch`,
      }
    : undefined;

/** Text colour for a themed slot, as the mod declared it. */
function inkFor(spec: ItemGridSpec, theme: Theme, slot: string, fallback: string): string {
  if (!theme[slot]) return fallback;
  return spec.themeInk[slot] === 'dark' ? 'text-[#2b2416]' : 'text-parchment';
}

/** The grid's own width, kept current as its host resizes. */
function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w != null) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function ItemGridField({
  spec,
  label,
  options,
  theme,
  value,
  onChange,
}: {
  spec: ItemGridSpec;
  label: string;
  options: ModConfigChoice[];
  theme: Theme;
  value: ItemGridValue;
  onChange: (next: ItemGridValue) => void;
}) {
  const t = useT();
  const [focus, setFocus] = useState<string | null>(null);
  const [rootRef, width] = useWidth<HTMLDivElement>();
  const themed = Object.values(theme).some(Boolean);
  const byId = new Map(options.map((o) => [o.id, o]));
  const focused = focus ? byId.get(focus) : undefined;
  const groups = groupSections(spec);

  // Pixels per rem, so the thresholds scale with the app's UI-scale setting.
  const rem =
    typeof document === 'undefined'
      ? 16
      : Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const perColumn = COLUMN_MIN_PX * (rem / 16);
  const asideRoom = ASIDE_PX * (rem / 16);
  const hasAside = Boolean(theme.portrait || spec.quote);
  const columns = spec.layout === 'columns' && width >= groups.length * perColumn;
  const asideBeside = columns && hasAside && width >= groups.length * perColumn + asideRoom;

  if (options.length === 0) {
    return (
      <p className="text-sm text-ash">
        {t('No options available.')} {t('Is Ravenswatch installed?')}
      </p>
    );
  }

  return (
    <div
      ref={rootRef}
      className={[
        'overflow-hidden rounded-lg',
        themed ? 'bg-[#161c22] text-parchment' : 'border border-border bg-pitch/40',
      ].join(' ')}
    >
      {spec.title || theme.title ? (
        <div className="flex h-14 items-center justify-center px-12" style={skin(theme.title)}>
          <span
            className={[
              'truncate font-fraktur text-xl drop-shadow',
              inkFor(spec, theme, 'title', 'text-parchment'),
            ].join(' ')}
          >
            {spec.title || label}
          </span>
        </div>
      ) : null}

      <div className={['flex gap-4 p-4', asideBeside ? 'flex-row' : 'flex-col'].join(' ')}>
        {hasAside ? (
          <aside
            className={[
              'flex shrink-0 gap-3',
              asideBeside ? 'w-48 flex-col' : 'flex-row items-center',
            ].join(' ')}
          >
            {theme.portrait ? (
              <img
                src={theme.portrait}
                alt=""
                className={[
                  'shrink-0 rounded-lg object-cover object-top',
                  asideBeside ? 'aspect-[4/5] w-full' : 'h-20 w-20',
                ].join(' ')}
              />
            ) : null}
            {spec.quote ? (
              <p
                className={[
                  'min-w-0 px-5 py-4 font-serif-italic text-sm leading-snug',
                  asideBeside ? '' : 'flex-1',
                  inkFor(spec, theme, 'quote', 'text-ash'),
                ].join(' ')}
                style={skin(theme.quote)}
              >
                {spec.quote}
              </p>
            ) : null}
          </aside>
        ) : null}

        <div
          className="grid min-w-0 flex-1 gap-y-4"
          style={
            columns
              ? {
                  gridTemplateColumns: groups
                    .map(() => 'minmax(0, 1fr)')
                    .join(theme.separator ? ' 0.75rem ' : ' 1rem '),
                }
              : undefined
          }
        >
          {groups.map(({ group, sections }, i) => (
            <Fragment key={`${group}:${sections[0]?.id}`}>
              {columns && i > 0 ? (
                <div
                  aria-hidden="true"
                  className="h-full w-full opacity-50"
                  style={skin(theme.separator)}
                />
              ) : null}
              <section className="flex min-w-0 flex-col gap-4 p-2.5" style={frame(theme.panel)}>
                {group ? (
                  <h4
                    className={[
                      'mx-auto max-w-full truncate px-8 py-1.5 text-center font-fraktur text-lg',
                      inkFor(spec, theme, 'header', 'text-gilt'),
                    ].join(' ')}
                    style={skin(theme.header)}
                  >
                    {group}
                  </h4>
                ) : null}
                {sections.map((section) => (
                  <GridSection
                    key={section.id}
                    spec={spec}
                    section={section}
                    options={options}
                    theme={theme}
                    value={value}
                    onChange={onChange}
                    onFocusItem={setFocus}
                  />
                ))}
              </section>
            </Fragment>
          ))}
        </div>
      </div>

      <div
        className={[
          'mx-4 mb-4 min-h-20 px-12 py-3',
          inkFor(spec, theme, 'details', 'rounded border border-border text-parchment'),
        ].join(' ')}
        style={skin(theme.details)}
        aria-live="polite"
      >
        {focused ? (
          <>
            <p className="font-fraktur text-lg">{focused.label}</p>
            {focused.description ? <p className="text-sm">{focused.description}</p> : null}
            {focused.group ? <p className="text-xs opacity-70">{focused.group}</p> : null}
          </>
        ) : (
          <p className="pt-3 text-center font-serif-italic text-sm opacity-80">
            {t('Point at an item to read it.')}
          </p>
        )}
      </div>
    </div>
  );
}

function GridSection({
  spec,
  section,
  options,
  theme,
  value,
  onChange,
  onFocusItem,
}: {
  spec: ItemGridSpec;
  section: ItemGridSection;
  options: ModConfigChoice[];
  theme: Theme;
  value: ItemGridValue;
  onChange: (next: ItemGridValue) => void;
  onFocusItem: (id: string | null) => void;
}) {
  const t = useT();
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState('');
  const byId = new Map(options.map((o) => [o.id, o]));
  const items = sectionItems(value, section, options);
  const count = sectionCount(value, section);
  const addable = candidates(value, section, options);
  const q = search.trim().toLowerCase();
  const shown = q
    ? addable.filter((o) => `${o.label} ${o.group} ${o.description}`.toLowerCase().includes(q))
    : addable;
  const changed = Boolean(value.sections?.[section.id]);

  return (
    <div className="min-w-0 space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <span className="min-w-0 truncate font-mono text-gilt text-xs">{section.label}</span>
        <span className="flex items-center gap-2">
          {changed ? (
            <button
              type="button"
              className="text-ash text-xs underline hover:text-parchment"
              onClick={() => onChange(withSectionReset(spec, value, options, section))}
            >
              {t('Restore this section')}
            </button>
          ) : null}
          <button
            type="button"
            aria-expanded={adding}
            disabled={addable.length === 0 && !adding}
            title={addable.length === 0 ? t('Nothing else fits here.') : undefined}
            onClick={() => setAdding((a) => !a)}
            className="btn-grim px-2 py-0.5 text-xs disabled:opacity-40"
          >
            {adding ? t('Close list') : `+ ${t('Add')}`}
          </button>
        </span>
      </div>

      {section.count && count != null ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded bg-black/25 px-2.5 py-1 text-xs">
          <span className="min-w-0 truncate text-ash">{section.count.label}</span>
          <span className="flex items-center gap-1.5">
            <button
              type="button"
              className="btn-grim px-2 py-0"
              aria-label={t('Decrease {label}', { label: section.count.label || section.label })}
              disabled={count <= section.count.min}
              onClick={() => onChange(withCount(spec, value, options, section, count - 1))}
            >
              −
            </button>
            <span className="w-5 text-center font-data text-sm">{count}</span>
            <button
              type="button"
              className="btn-grim px-2 py-0"
              aria-label={t('Increase {label}', { label: section.count.label || section.label })}
              disabled={count >= Math.min(section.count.max, items.length)}
              onClick={() => onChange(withCount(spec, value, options, section, count + 1))}
            >
              +
            </button>
          </span>
        </div>
      ) : null}

      {adding ? (
        <div className="space-y-2 rounded-md border border-gilt/30 bg-black/50 p-2">
          <Input
            type="search"
            value={search}
            placeholder={t('Search {n} options…', { n: addable.length })}
            onChange={(e) => setSearch(e.target.value)}
          />
          {addable.length === 0 ? (
            <p className="p-2 text-center text-ash text-xs">{t('Nothing else fits here.')}</p>
          ) : (
            <ul className="max-h-60 space-y-0.5 overflow-y-auto">
              {shown.map((o) => (
                <li key={o.id}>
                  <button
                    type="button"
                    onClick={() =>
                      onChange(withItems(spec, value, options, section.id, [...items, o.id]))
                    }
                    onMouseEnter={() => onFocusItem(o.id)}
                    onFocus={() => onFocusItem(o.id)}
                    className="flex w-full min-w-0 items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-gilt/15"
                  >
                    {o.icon ? <img src={o.icon} alt="" className="h-8 w-8 shrink-0" /> : null}
                    <span className="min-w-0">
                      <span className="block truncate text-sm">{o.label}</span>
                      {o.group ? (
                        <span className="block truncate text-ash text-xs">{o.group}</span>
                      ) : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {items.length === 0 && section.empty ? (
        <p className="rounded-md border border-gilt/25 border-dashed px-3 py-4 text-center font-serif-italic text-ash text-sm">
          {section.empty}
        </p>
      ) : null}

      <ul className="grid grid-cols-[repeat(auto-fill,minmax(5.75rem,7.5rem))] gap-2">
        {items.map((id) => (
          <GridCard
            key={id}
            spec={spec}
            id={id}
            option={byId.get(id)}
            theme={theme}
            value={value}
            options={options}
            removable={items.length > minItems(section)}
            onRemove={() =>
              onChange(
                withItems(
                  spec,
                  value,
                  options,
                  section.id,
                  items.filter((x) => x !== id),
                ),
              )
            }
            onChange={onChange}
            onFocusItem={onFocusItem}
          />
        ))}
      </ul>
    </div>
  );
}

function GridCard({
  spec,
  id,
  option,
  theme,
  value,
  options,
  removable,
  onRemove,
  onChange,
  onFocusItem,
}: {
  spec: ItemGridSpec;
  id: string;
  option: ModConfigChoice | undefined;
  theme: Theme;
  value: ItemGridValue;
  options: ModConfigChoice[];
  removable: boolean;
  onRemove: () => void;
  onChange: (next: ItemGridValue) => void;
  onFocusItem: (id: string | null) => void;
}) {
  const t = useT();
  const [hoverRemove, setHoverRemove] = useState(false);
  const label = option?.label ?? id;
  const n = option ? optionNumber(spec, value, option) : null;
  const editable = option ? numberEditable(spec, option) : false;
  const numberLabel = spec.number?.label || t('Value');

  return (
    <li
      className="group relative flex min-w-0 flex-col items-center gap-1.5 rounded-md bg-gradient-to-b from-[#3a4855] to-[#20272e] px-1.5 pt-2.5 pb-2 shadow-md ring-1 ring-gilt/50 transition hover:ring-gilt"
      onMouseEnter={() => onFocusItem(id)}
    >
      {removable ? (
        <button
          type="button"
          aria-label={t('Remove {name}', { name: label })}
          title={t('Remove {name}', { name: label })}
          onClick={onRemove}
          onFocus={() => onFocusItem(id)}
          onMouseEnter={() => setHoverRemove(true)}
          onMouseLeave={() => setHoverRemove(false)}
          className="absolute top-1 right-1 flex h-5 w-5 items-center justify-center rounded text-ash text-xs opacity-60 transition hover:text-crimson hover:opacity-100 group-hover:opacity-100"
          style={skin(hoverRemove ? theme.removeHover || theme.remove : theme.remove)}
        >
          {theme.remove ? null : '✕'}
        </button>
      ) : null}
      {option?.icon ? (
        <img src={option.icon} alt="" className="h-14 w-14 object-contain drop-shadow" />
      ) : (
        <span className="flex h-14 w-14 items-center justify-center text-ash text-sm">
          {label.slice(0, 2).toUpperCase()}
        </span>
      )}
      <span className="line-clamp-2 min-h-8 w-full break-words text-center text-[0.7rem] leading-tight">
        {label}
      </span>
      {spec.number && n != null ? (
        <span
          className="flex max-w-full items-center gap-1 rounded-full bg-black/55 px-2 py-0.5 ring-1 ring-gilt/40"
          style={skin(theme.number)}
          title={
            editable
              ? t('{label} of {name}', { label: numberLabel, name: label })
              : t('The {label} of {name} cannot be changed here.', {
                  label: numberLabel,
                  name: label,
                })
          }
        >
          {theme.numberIcon ? (
            <img src={theme.numberIcon} alt="" className="h-3.5 w-3.5 shrink-0" />
          ) : null}
          {editable ? (
            <input
              type="number"
              min={spec.number.min}
              max={spec.number.max}
              step={1}
              aria-label={t('{label} of {name}', { label: numberLabel, name: label })}
              value={n}
              onFocus={() => onFocusItem(id)}
              onChange={(e) => {
                const next = Number.parseInt(e.target.value, 10);
                if (Number.isFinite(next)) onChange(withNumber(spec, value, options, id, next));
              }}
              className="w-10 min-w-0 appearance-none bg-transparent text-center font-data text-[#f3e3a8] text-xs focus:outline-none [&::-webkit-inner-spin-button]:appearance-none"
            />
          ) : (
            <span className="w-10 text-center font-data text-ash text-xs">{n}</span>
          )}
        </span>
      ) : null}
    </li>
  );
}
