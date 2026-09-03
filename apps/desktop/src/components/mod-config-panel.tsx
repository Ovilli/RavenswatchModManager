import { Input } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, type ReactNode, useEffect, useMemo, useState } from 'react';
import { t as tr } from '../lib/i18n';
import { useT } from '../lib/i18n-react';
import { inTauri } from '../lib/platform';
import { type ModConfigChoice, type ModConfigField, getModConfig, setModConfig } from '../lib/rsmm';
import { Button, Fleuron, InkSwitch, Panel } from './chrome';

type ConfigValue = boolean | number | string | string[];

export function ModConfigPanel({
  modId,
  modName,
  enabled,
  onToggleEnabled,
  onDirtyChange,
  frameless,
}: {
  modId: string;
  modName: string;
  enabled?: boolean;
  onToggleEnabled?: () => void;
  onDirtyChange?: (modId: string, dirty: boolean) => void;
  /** Drop the panel's own card chrome — for a host that already draws one
   * (the per-mod config dialog), where nesting two cards doubles the border. */
  frameless?: boolean;
}) {
  const t = useT();
  const queryClient = useQueryClient();
  const Shell = frameless ? FramelessShell : Panel;
  const [draft, setDraft] = useState<Record<string, ConfigValue>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  const configQuery = useQuery({
    queryKey: ['mods', 'config', modId],
    queryFn: async () => {
      const result = await getModConfig(modId);
      if (!result.ok) {
        throw new Error(result.error || `Could not load config for ${modName}`);
      }
      return result;
    },
    enabled: inTauri(),
    staleTime: 30_000,
  });
  const schemaFields = configQuery.data?.schema?.fields;

  useEffect(() => {
    if (!configQuery.data?.values) return;
    if (!schemaFields) return;
    setDraft(buildDraft(schemaFields, configQuery.data.values));
    setTouched({});
  }, [configQuery.data?.values, schemaFields]);

  const saveMutation = useMutation({
    mutationFn: async (values: Record<string, ConfigValue>) => {
      const result = await setModConfig(modId, values);
      if (!result.ok) {
        throw new Error(result.error || `Could not save config for ${modName}`);
      }
      return result;
    },
    onSuccess: (result) => {
      queryClient.setQueryData(['mods', 'config', modId], result);
      if (result.schema?.fields && result.values) {
        setDraft(buildDraft(result.schema.fields, result.values));
      } else if (result.values) {
        setDraft(result.values);
      }
      setTouched({});
      queryClient
        .invalidateQueries({ queryKey: ['mods', 'config', modId] })
        .catch((e) => console.error('[mod-config] failed to refresh config after save', e));
    },
  });

  const schema = configQuery.data?.schema?.fields ?? {};
  const keys = Object.keys(schema);
  const loadedValues = configQuery.data?.values ?? {};
  // Options for provider-backed `multiselect` fields, resolved by the CLI and
  // delivered with the schema so the panel draws labels and art in one trip.
  const choices: Record<string, ModConfigChoice[]> = configQuery.data?.choices ?? {};
  // A provider-backed field picks from the game's own catalog (items, so far),
  // and `apply` turns that selection into rewritten cooked assets. That is the
  // edit that costs a rebuild on the next launch, so it gets the louder wording.
  const cooksAssets = Object.values(schemaFields ?? {}).some((f) => Boolean(f.source));
  const defaults = useMemo(() => buildDefaultDraft(schema), [schema]);
  const loadedDraft = useMemo(() => buildDraft(schema, loadedValues), [schema, loadedValues]);
  const validation = useMemo(
    () => validateConfigDraft(schema, draft, touched),
    [draft, schema, touched],
  );
  const loadedValidation = useMemo(
    () => validateConfigDraft(schema, loadedDraft, {}),
    [loadedDraft, schema],
  );
  const isDirty = useMemo(
    () =>
      JSON.stringify(orderConfigValues(schema, validation.normalized)) !==
      JSON.stringify(orderConfigValues(schema, loadedValidation.normalized)),
    [loadedValidation.normalized, schema, validation.normalized],
  );

  useEffect(() => {
    onDirtyChange?.(modId, isDirty);
    return () => onDirtyChange?.(modId, false);
  }, [isDirty, onDirtyChange, modId]);

  useEffect(() => {
    if (!isDirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [isDirty]);

  if (configQuery.isLoading) {
    return (
      <Shell>
        <h3 className="font-fraktur text-xl text-parchment mb-3">{t('Config')}</h3>
        <Fleuron />
        {/* Say what the wait IS. A field backed by a catalog provider decodes
            every icon out of the cooked game files on first open, which is a
            few seconds of staring at a pulsing box otherwise. */}
        <p className="mt-4 font-mono text-ash" aria-live="polite">
          {t(
            'Reading config… a mod that lists game content decodes its art from the install, so the first open can take a few seconds.',
          )}
        </p>
        <div className="mt-3 space-y-3 animate-pulse" aria-busy="true">
          <div className="h-10 rounded bg-oxblood/15" />
          <div className="h-10 rounded bg-oxblood/15" />
        </div>
      </Shell>
    );
  }

  if (configQuery.error) {
    return (
      <Shell>
        <h3 className="font-fraktur text-xl text-parchment mb-3">{t('Config')}</h3>
        <Fleuron />
        <p className="mt-4 text-sm text-ash">{configQuery.error.message}</p>
      </Shell>
    );
  }

  if (!keys.length) {
    return (
      <Shell>
        <h3 className="font-fraktur text-xl text-parchment mb-3">{t('Config')}</h3>
        <Fleuron />
        <p className="mt-4 text-sm text-ash">
          {t('This mod does not declare any editable config fields.')}
        </p>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-fraktur text-xl text-parchment mb-3">{t('Config')}</h3>
          <Fleuron />
        </div>
        <div className="flex items-center gap-2">
          {enabled != null && onToggleEnabled ? (
            <InkSwitch
              on={enabled}
              onClick={onToggleEnabled}
              label={
                enabled
                  ? t('Disable {name}', { name: modName })
                  : t('Enable {name}', { name: modName })
              }
            />
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="danger"
            onClick={() => {
              setDraft(cloneConfigValues(defaults));
              setTouched({});
            }}
            disabled={!isDirty || saveMutation.isPending}
          >
            {t('Reset to defaults')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => saveMutation.mutate(validation.normalized)}
            disabled={!isDirty || saveMutation.isPending || validation.hasErrors}
          >
            {saveMutation.isPending ? t('Saving…') : t('Save')}
          </Button>
        </div>
      </div>

      {validation.summary ? (
        <p className="mt-3 rounded border border-crimson/40 bg-crimson/10 px-3 py-2 text-sm text-crimson">
          {validation.summary}
        </p>
      ) : null}

      <div className="mt-4 space-y-4">
        {keys.map((key) => {
          const field = schema[key];
          if (!field) return null;
          return (
            <ConfigFieldRow
              key={key}
              name={key}
              field={field}
              choices={choices[key]}
              siblings={siblingBuckets(schema, key)}
              value={draft[key] ?? loadedValues[key] ?? fieldFallback(field)}
              error={validation.errors[key]}
              onChange={(next) => {
                setDraft((current) => ({ ...current, [key]: next }));
                setTouched((current) => ({ ...current, [key]: true }));
              }}
              onMove={(optionId, target) => {
                setDraft((current) => {
                  const from = asIds(current[key]).filter((x) => x !== optionId);
                  const to = [...new Set([...asIds(current[target]), optionId])].sort();
                  return { ...current, [key]: from, [target]: to };
                });
                setTouched((current) => ({ ...current, [key]: true, [target]: true }));
              }}
            />
          );
        })}
      </div>

      {saveMutation.error ? (
        <p className="mt-4 text-sm text-crimson">{saveMutation.error.message}</p>
      ) : null}

      {/* Nothing here is hot-reloaded: the loader hands a mod its config once,
          at load, and any config that feeds COOKED content is baked into the
          game's asset files by the `apply` that runs on Play. So a saved value
          reaches a running game never — it needs a full quit and relaunch. */}
      {saveMutation.isSuccess && !isDirty ? (
        <div className="ember-banner mt-4 px-4 py-3">
          <p className="font-serif-italic text-base">
            {t('Saved — the running game will not see it.')}
          </p>
          <p className="font-mono mt-1 text-ash">
            {t('Quit Ravenswatch completely, then press Play.')}{' '}
            {cooksAssets
              ? t('Launch rebuilds the affected game assets first, which takes a moment.')
              : t('The mod reads its config when the game loads it.')}
          </p>
        </div>
      ) : (
        <p className="font-mono mt-4 text-ash">
          {cooksAssets
            ? t(
                'Config is read at game load and baked into game assets on launch — changes need a full game restart, not just a new run.',
              )
            : t(
                'Config is read at game load — changes need a full game restart, not just a new run.',
              )}
        </p>
      )}
    </Shell>
  );
}

function FramelessShell({ children }: { children: ReactNode }) {
  return <div>{children}</div>;
}

/** Per-group accent, cycled by the order groups first appear.
 *
 * A provider groups its options by something the player thinks in — the
 * chapter a monster ships in, the rarity of an item — and that grouping is the
 * only structure a 50-row list has. Rendering it as one grey column threw it
 * away: a chip in the Dark Hills list gave no hint it was a Storm Island crab,
 * which is exactly what the cross-chapter picking is for. Full class strings,
 * because Tailwind's scanner cannot see an interpolated one.
 */
const GROUP_TONES = [
  { dot: 'bg-gilt', text: 'text-gilt', edge: 'border-l-gilt/70', chip: 'border-gilt/50 bg-gilt/10' },
  {
    dot: 'bg-crimson',
    text: 'text-crimson',
    edge: 'border-l-crimson/70',
    chip: 'border-crimson/50 bg-crimson/10',
  },
  {
    dot: 'bg-frost',
    text: 'text-frost',
    edge: 'border-l-frost/70',
    chip: 'border-frost/50 bg-frost/10',
  },
  { dot: 'bg-moss', text: 'text-moss', edge: 'border-l-moss/70', chip: 'border-moss/50 bg-moss/10' },
  {
    dot: 'bg-smoke',
    text: 'text-smoke',
    edge: 'border-l-smoke/70',
    chip: 'border-smoke/50 bg-smoke/10',
  },
] as const;

function toneOf(groups: string[], group: string) {
  const i = groups.indexOf(group);
  return GROUP_TONES[(i < 0 ? 0 : i) % GROUP_TONES.length] ?? GROUP_TONES[0];
}

function MultiSelectField({
  id,
  field,
  choices,
  siblings,
  value,
  onChange,
  onMove,
}: {
  id: string;
  field: ModConfigField;
  choices: ModConfigChoice[];
  /** Other same-source multiselect fields, offered as move destinations. */
  siblings: { name: string; label: string }[];
  value: string[];
  onChange: (next: string[]) => void;
  onMove?: (optionId: string, target: string) => void;
}) {
  const t = useT();
  const [search, setSearch] = useState('');

  // A field with no provider still works: its static `choices` become plain
  // options with no art, so the same control serves both kinds.
  const options: ModConfigChoice[] =
    choices.length > 0
      ? choices
      : field.choices.map((c) => ({ id: c, label: c, group: '', icon: '', description: '' }));

  const q = search.trim().toLowerCase();
  const shown = q
    ? options.filter((o) => `${o.label} ${o.id} ${o.description}`.toLowerCase().includes(q))
    : options;

  const selected = new Set(value);
  const toggle = (oid: string) => {
    const next = new Set(selected);
    if (next.has(oid)) next.delete(oid);
    else next.add(oid);
    onChange([...next].sort());
  };

  // Options arrive already grouped and sorted, so a heading is emitted
  // whenever the neighbour's group differs — no second pass over the list.
  let lastGroup: string | null = null;

  if (options.length === 0) {
    return (
      <p className="text-sm text-ash">
        {t('No options available.')} {field.source ? t('Is Ravenswatch installed?') : null}
      </p>
    );
  }

  const byId = new Map(options.map((o) => [o.id, o]));
  const labelOf = (oid: string) => byId.get(oid)?.label || oid;
  // Order of first appearance, so a group keeps its colour as the search
  // narrows the list — a tone that moved while typing would be worse than none.
  const groupOrder: string[] = [];
  for (const o of options) {
    if (o.group && !groupOrder.includes(o.group)) groupOrder.push(o.group);
  }

  return (
    <div className="space-y-2">
      {/* What is IN the list, as its own row.
          Without it the only record of a selection is a tick somewhere in a
          50-row scroller, so removing one meant hunting for it and moving one
          to another chapter meant hunting twice.

          The move control is SPELLED OUT rather than drawn as an arrow. It was
          a bare ▾ glyph inside a small chip first, and nothing about that says
          "this sends the monster to another chapter" — the one action here that
          is not guessable from the list itself. It gets a word, a box, and a
          sentence above the row saying what the two controls do. */}
      {value.length > 0 ? (
        <div className="space-y-1.5 rounded border border-border bg-pitch/30 p-2">
          <p className="text-ash text-xs">
            {onMove && siblings.length > 0
              ? t('In this list — “Move to” sends one to another list, ✕ removes it.')
              : t('In this list — ✕ removes one.')}
          </p>
          <ul className="flex flex-wrap gap-2">
            {value.map((oid) => (
              <li
                key={oid}
                className={[
                  'flex items-center gap-2 rounded-full border py-1 pl-2.5 pr-1.5 text-parchment text-sm',
                  toneOf(groupOrder, byId.get(oid)?.group ?? '').chip,
                ].join(' ')}
                title={byId.get(oid)?.group || undefined}
              >
                <span
                  className={[
                    'h-2 w-2 shrink-0 rounded-full',
                    toneOf(groupOrder, byId.get(oid)?.group ?? '').dot,
                  ].join(' ')}
                  aria-hidden="true"
                />
                <span className="max-w-56 truncate">{labelOf(oid)}</span>
                {onMove && siblings.length > 0 ? (
                  <select
                    aria-label={t('Move {name} to another list', { name: labelOf(oid) })}
                    title={t('Move {name} to another list', { name: labelOf(oid) })}
                    value=""
                    onChange={(e) => {
                      if (e.target.value) onMove(oid, e.target.value);
                    }}
                    className="select-inline rounded-full border border-ash/40 px-2 py-0.5 text-xs hover:border-gilt/60"
                  >
                    <option value="">{t('Move to ▾')}</option>
                    {siblings.map((sib) => (
                      <option key={sib.name} value={sib.name}>
                        {sib.label}
                      </option>
                    ))}
                  </select>
                ) : null}
                <button
                  type="button"
                  aria-label={t('Remove {name}', { name: labelOf(oid) })}
                  title={t('Remove {name}', { name: labelOf(oid) })}
                  onClick={() => onChange(value.filter((x) => x !== oid))}
                  className="rounded-full px-1 text-ash text-base leading-none hover:text-crimson"
                >
                  {'\u2715'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="search"
          value={search}
          placeholder={t('Search {n} options…', { n: options.length })}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1"
        />
        <span className="whitespace-nowrap text-xs text-ash">
          {t('{n} selected', { n: selected.size })}
        </span>
        {selected.size > 0 ? (
          <button
            type="button"
            onClick={() => onChange([])}
            className="whitespace-nowrap text-xs text-ash underline hover:text-parchment"
          >
            {t('Clear')}
          </button>
        ) : null}
      </div>

      <div className="max-h-96 space-y-2 overflow-y-auto rounded border border-border bg-pitch/40 p-2">
        {shown.length === 0 ? (
          <p className="p-2 text-center text-sm text-ash">
            {t('Nothing matches “{query}”.', { query: search })}
          </p>
        ) : (
          shown.map((opt) => {
            const on = selected.has(opt.id);
            const heading = opt.group && opt.group !== lastGroup ? opt.group : null;
            lastGroup = opt.group || lastGroup;
            const tone = toneOf(groupOrder, opt.group);
            return (
              <Fragment key={opt.id}>
                {heading ? (
                  <p
                    className={[
                      'px-1 pt-2 font-fraktur text-xs uppercase tracking-wide',
                      tone.text,
                    ].join(' ')}
                  >
                    {heading}
                  </p>
                ) : null}
                <button
                  type="button"
                  aria-pressed={on}
                  title={opt.description || opt.id}
                  onClick={() => toggle(opt.id)}
                  className={[
                    'flex w-full items-center gap-3 rounded border-l-2 px-2 py-1.5 text-left transition',
                    tone.edge,
                    on
                      ? 'bg-crimson/20 text-parchment'
                      : 'text-parchment/80 hover:bg-char/40 hover:text-parchment',
                  ].join(' ')}
                >
                  {opt.icon ? (
                    <img
                      src={opt.icon}
                      alt=""
                      className={['h-8 w-8 shrink-0 object-contain', on ? 'grayscale' : ''].join(
                        ' ',
                      )}
                    />
                  ) : (
                    // No art for this catalog (enemy prefabs have none), so the
                    // group's own colour stands in — the row is never blank and
                    // never uniform grey.
                    <span
                      className={[
                        'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-[0.65rem]',
                        on ? 'border-crimson/60' : 'border-border',
                        tone.text,
                      ].join(' ')}
                      aria-hidden="true"
                    >
                      {(opt.label || opt.id).slice(0, 2).toUpperCase()}
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{opt.label}</span>
                    {opt.description ? (
                      <span className="block truncate text-ash text-xs">{opt.description}</span>
                    ) : null}
                  </span>
                  <span
                    className={[
                      'flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border text-[0.6rem]',
                      on ? 'border-crimson bg-crimson/40 text-parchment' : 'border-ash/50',
                    ].join(' ')}
                  >
                    {on ? '\u2715' : ''}
                  </span>
                </button>
              </Fragment>
            );
          })
        )}
      </div>
    </div>
  );
}

function ConfigFieldRow({
  name,
  field,
  value,
  error,
  choices,
  siblings,
  onChange,
  onMove,
}: {
  name: string;
  field: ModConfigField;
  value: ConfigValue;
  error?: string;
  choices?: ModConfigChoice[];
  siblings?: { name: string; label: string }[];
  onChange: (value: ConfigValue) => void;
  onMove?: (optionId: string, target: string) => void;
}) {
  const t = useT();
  const id = `config-${name}`;
  const label = field.label || name;

  return (
    <label htmlFor={id} className="block space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="font-data text-sm text-parchment">{label}</span>
        {field.type === 'enum' && field.choices.length > 0 ? (
          <span className="font-data text-xs text-ash">{field.choices.join(' · ')}</span>
        ) : field.type === 'int' || field.type === 'float' ? (
          <span className="font-mono text-xs text-ash">
            {field.min != null ? t('min {value}', { value: field.min }) : ''}
            {field.min != null && field.max != null ? ' · ' : ''}
            {field.max != null ? t('max {value}', { value: field.max }) : ''}
          </span>
        ) : null}
      </div>

      {field.type === 'multiselect' ? (
        <MultiSelectField
          id={id}
          field={field}
          choices={choices ?? []}
          siblings={siblings ?? []}
          value={Array.isArray(value) ? value : []}
          onChange={onChange}
          onMove={onMove}
        />
      ) : field.type === 'bool' ? (
        <div className="flex items-center gap-2">
          <input
            id={id}
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
            className="h-4 w-4 rounded border-border bg-pitch/60 text-gilt focus:ring-gilt/40"
          />
          <span className="text-sm text-ash">{value ? t('Enabled') : t('Disabled')}</span>
        </div>
      ) : field.type === 'enum' ? (
        <select
          id={id}
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className="select-grim font-mono w-full border border-border bg-pitch/60 px-3 py-2 text-sm text-parchment focus:border-gilt/60 focus:outline-none"
        >
          {field.choices.length > 0 ? (
            field.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))
          ) : (
            <option value={String(value)}>{String(value)}</option>
          )}
        </select>
      ) : field.type === 'string' ? (
        <Input
          id={id}
          type="text"
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          className="font-mono"
        />
      ) : (
        <Input
          id={id}
          type="number"
          inputMode={field.type === 'int' ? 'numeric' : 'decimal'}
          step={field.type === 'int' ? 1 : 'any'}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          className="font-mono"
        />
      )}
      {error ? <p className="text-xs text-crimson">{error}</p> : null}
    </label>
  );
}

/** The other `multiselect` fields drawing from the same option provider.
 *
 * Same source = same universe of options, which is what makes "move this one
 * to that list" meaningful: for `random-monsters` the four fields are four
 * chapters over one roster, and moving a monster between chapters is the edit
 * people actually make. Fields with no source (or a different one) are not
 * buckets of the same thing and are never offered as a destination.
 */
function siblingBuckets(
  fields: Record<string, ModConfigField>,
  key: string,
): { name: string; label: string }[] {
  const self = fields[key];
  if (!self || self.type !== 'multiselect' || !self.source) return [];
  return Object.entries(fields)
    .filter(([name, f]) => name !== key && f.type === 'multiselect' && f.source === self.source)
    .map(([name, f]) => ({ name, label: f.label || name }));
}

function asIds(value: ConfigValue | undefined): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function cloneConfigValues(values: Record<string, ConfigValue>): Record<string, ConfigValue> {
  return Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v])) as Record<
    string,
    ConfigValue
  >;
}

function fieldFallback(field: ModConfigField): ConfigValue {
  if (field.type === 'multiselect') {
    return Array.isArray(field.default) ? [...field.default] : [];
  }
  if (field.default != null) return field.default as ConfigValue;
  if (field.type === 'bool') return false;
  return '';
}

function buildDefaultDraft(fields: Record<string, ModConfigField>): Record<string, ConfigValue> {
  const out: Record<string, ConfigValue> = {};
  for (const [key, field] of Object.entries(fields)) {
    out[key] = fieldFallback(field);
  }
  return out;
}

function buildDraft(
  fields: Record<string, ModConfigField>,
  values: Record<string, ConfigValue>,
): Record<string, ConfigValue> {
  const out: Record<string, ConfigValue> = {};
  for (const [key, field] of Object.entries(fields)) {
    out[key] = values[key] ?? fieldFallback(field);
  }
  return out;
}

function orderConfigValues(
  fields: Record<string, ModConfigField>,
  values: Record<string, ConfigValue>,
): Record<string, ConfigValue> {
  const out: Record<string, ConfigValue> = {};
  for (const key of Object.keys(fields)) {
    const current = values[key];
    if (current !== undefined) out[key] = current;
  }
  return out;
}

function validateConfigDraft(
  fields: Record<string, ModConfigField>,
  draft: Record<string, ConfigValue>,
  touched: Record<string, boolean>,
): {
  normalized: Record<string, ConfigValue>;
  errors: Record<string, string>;
  hasErrors: boolean;
  summary: string;
} {
  const normalized: Record<string, ConfigValue> = {};
  const errors: Record<string, string> = {};
  for (const [key, field] of Object.entries(fields)) {
    const raw = draft[key];
    const parsed = validateField(field, raw, touched[key] ?? false);
    if ('error' in parsed) {
      errors[key] = parsed.error;
      normalized[key] = fieldFallback(field);
    } else {
      normalized[key] = parsed.value;
    }
  }
  const errorCount = Object.keys(errors).length;
  return {
    normalized,
    errors,
    hasErrors: errorCount > 0,
    // Plain functions, so they use the module-level translator rather than the
    // hook. A language switch replaces the settings object, which re-renders
    // the panel, so these strings are re-derived in the new language.
    summary: errorCount
      ? errorCount === 1
        ? tr('{n} field needs attention before saving.', { n: errorCount })
        : tr('{n} fields need attention before saving.', { n: errorCount })
      : '',
  };
}

function validateField(
  field: ModConfigField,
  raw: ConfigValue | undefined,
  touched: boolean,
): { value: ConfigValue } | { error: string } {
  if (field.type === 'bool') {
    return { value: Boolean(raw) };
  }
  if (field.type === 'string') {
    return { value: raw == null ? '' : String(raw) };
  }
  if (field.type === 'multiselect') {
    // A provider-backed field's valid ids live in the game install and may be
    // unreadable here, so membership is not enforced client-side — dropping an
    // id we merely cannot see right now would silently discard the selection.
    return { value: Array.isArray(raw) ? raw.map(String) : [] };
  }
  if (field.type === 'enum') {
    const value = raw == null ? '' : String(raw);
    if (!touched && value === '' && field.default == null) {
      return { value };
    }
    if (field.choices.length > 0 && !field.choices.includes(value)) {
      return {
        error:
          field.choices.length === 1
            ? tr('Choose {value}.', { value: field.choices[0] ?? '' })
            : tr('Choose one of: {list}.', { list: field.choices.join(', ') }),
      };
    }
    return { value };
  }

  const text = raw == null ? '' : String(raw).trim();
  if (!text) {
    if (!touched && field.default == null) {
      return { value: fieldFallback(field) };
    }
    return { error: tr('Enter a value.') };
  }
  const parsed = field.type === 'int' ? Number.parseInt(text, 10) : Number.parseFloat(text);
  if (!Number.isFinite(parsed) || (field.type === 'int' && !Number.isInteger(parsed))) {
    return {
      error: field.type === 'int' ? tr('Enter a whole number.') : tr('Enter a valid number.'),
    };
  }
  if (field.min != null && parsed < field.min) {
    return { error: tr('Must be at least {value}.', { value: field.min }) };
  }
  if (field.max != null && parsed > field.max) {
    return { error: tr('Must be at most {value}.', { value: field.max }) };
  }
  return { value: parsed };
}
