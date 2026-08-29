import { Input } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, type ReactNode, useEffect, useMemo, useState } from 'react';
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
        <h3 className="font-fraktur text-xl text-parchment mb-3">Config</h3>
        <Fleuron />
        {/* Say what the wait IS. A field backed by a catalog provider decodes
            every icon out of the cooked game files on first open, which is a
            few seconds of staring at a pulsing box otherwise. */}
        <p className="mt-4 font-mono text-ash" aria-live="polite">
          Reading config… a mod that lists game content decodes its art from the install, so the
          first open can take a few seconds.
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
        <h3 className="font-fraktur text-xl text-parchment mb-3">Config</h3>
        <Fleuron />
        <p className="mt-4 text-sm text-ash">{configQuery.error.message}</p>
      </Shell>
    );
  }

  if (!keys.length) {
    return (
      <Shell>
        <h3 className="font-fraktur text-xl text-parchment mb-3">Config</h3>
        <Fleuron />
        <p className="mt-4 text-sm text-ash">
          This mod does not declare any editable config fields.
        </p>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-fraktur text-xl text-parchment mb-3">Config</h3>
          <Fleuron />
        </div>
        <div className="flex items-center gap-2">
          {enabled != null && onToggleEnabled ? (
            <InkSwitch
              on={enabled}
              onClick={onToggleEnabled}
              label={`${enabled ? 'Disable' : 'Enable'} ${modName}`}
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
            Reset to defaults
          </Button>
          <Button
            type="button"
            size="sm"
            variant="primary"
            onClick={() => saveMutation.mutate(validation.normalized)}
            disabled={!isDirty || saveMutation.isPending || validation.hasErrors}
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
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
              value={draft[key] ?? loadedValues[key] ?? fieldFallback(field)}
              error={validation.errors[key]}
              onChange={(next) => {
                setDraft((current) => ({ ...current, [key]: next }));
                setTouched((current) => ({ ...current, [key]: true }));
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
          <p className="font-serif-italic text-base">Saved — the running game will not see it.</p>
          <p className="font-mono mt-1 text-ash">
            Quit Ravenswatch completely, then press Play.{' '}
            {cooksAssets
              ? 'Launch rebuilds the affected game assets first, which takes a moment.'
              : 'The mod reads its config when the game loads it.'}
          </p>
        </div>
      ) : (
        <p className="font-mono mt-4 text-ash">
          Config is read at game load{cooksAssets ? ' and baked into game assets on launch' : ''} —
          changes need a full game restart, not just a new run.
        </p>
      )}
    </Shell>
  );
}

function FramelessShell({ children }: { children: ReactNode }) {
  return <div>{children}</div>;
}

function MultiSelectField({
  id,
  field,
  choices,
  value,
  onChange,
}: {
  id: string;
  field: ModConfigField;
  choices: ModConfigChoice[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
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
        No options available. {field.source ? 'Is Ravenswatch installed?' : null}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="search"
          value={search}
          placeholder={`Search ${options.length} options…`}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1"
        />
        <span className="whitespace-nowrap text-xs text-ash">{selected.size} selected</span>
        {selected.size > 0 ? (
          <button
            type="button"
            onClick={() => onChange([])}
            className="whitespace-nowrap text-xs text-ash underline hover:text-parchment"
          >
            Clear
          </button>
        ) : null}
      </div>

      <div className="max-h-96 space-y-2 overflow-y-auto rounded border border-border bg-pitch/40 p-2">
        {shown.length === 0 ? (
          <p className="p-2 text-center text-sm text-ash">Nothing matches “{search}”.</p>
        ) : (
          shown.map((opt) => {
            const on = selected.has(opt.id);
            const heading = opt.group && opt.group !== lastGroup ? opt.group : null;
            lastGroup = opt.group || lastGroup;
            return (
              <Fragment key={opt.id}>
                {heading ? (
                  <p className="px-1 pt-2 font-fraktur text-ash text-xs uppercase tracking-wide">
                    {heading}
                  </p>
                ) : null}
                <button
                  type="button"
                  aria-pressed={on}
                  title={opt.description || opt.id}
                  onClick={() => toggle(opt.id)}
                  className={[
                    'flex w-full items-center gap-3 rounded px-2 py-1.5 text-left transition',
                    on ? 'bg-crimson/20 text-parchment' : 'hover:bg-char/40 text-smoke',
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
                    <span className="h-8 w-8 shrink-0" />
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
  onChange,
}: {
  name: string;
  field: ModConfigField;
  value: ConfigValue;
  error?: string;
  choices?: ModConfigChoice[];
  onChange: (value: ConfigValue) => void;
}) {
  const id = `config-${name}`;
  const label = field.label || name;

  return (
    <label htmlFor={id} className="block space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-sm text-parchment">{label}</span>
        {field.type === 'enum' && field.choices.length > 0 ? (
          <span className="font-mono text-xs text-ash">{field.choices.join(' · ')}</span>
        ) : field.type === 'int' || field.type === 'float' ? (
          <span className="font-mono text-xs text-ash">
            {field.min != null ? `min ${field.min}` : ''}
            {field.min != null && field.max != null ? ' · ' : ''}
            {field.max != null ? `max ${field.max}` : ''}
          </span>
        ) : null}
      </div>

      {field.type === 'multiselect' ? (
        <MultiSelectField
          id={id}
          field={field}
          choices={choices ?? []}
          value={Array.isArray(value) ? value : []}
          onChange={onChange}
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
          <span className="text-sm text-ash">{value ? 'Enabled' : 'Disabled'}</span>
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
    summary: errorCount
      ? `${errorCount} field${errorCount === 1 ? '' : 's'} need attention before saving.`
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
            ? `Choose ${field.choices[0]}.`
            : `Choose one of: ${field.choices.join(', ')}.`,
      };
    }
    return { value };
  }

  const text = raw == null ? '' : String(raw).trim();
  if (!text) {
    if (!touched && field.default == null) {
      return { value: fieldFallback(field) };
    }
    return { error: 'Enter a value.' };
  }
  const parsed = field.type === 'int' ? Number.parseInt(text, 10) : Number.parseFloat(text);
  if (!Number.isFinite(parsed) || (field.type === 'int' && !Number.isInteger(parsed))) {
    return { error: field.type === 'int' ? 'Enter a whole number.' : 'Enter a valid number.' };
  }
  if (field.min != null && parsed < field.min) {
    return { error: `Must be at least ${field.min}.` };
  }
  if (field.max != null && parsed > field.max) {
    return { error: `Must be at most ${field.max}.` };
  }
  return { value: parsed };
}
