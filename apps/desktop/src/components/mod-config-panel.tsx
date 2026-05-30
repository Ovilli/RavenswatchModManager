import { Input } from '@rsmm/ui';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { inTauri } from '../lib/platform';
import { type ModConfigField, getModConfig, setModConfig } from '../lib/rsmm';
import { Button, Fleuron, InkSwitch, Panel } from './chrome';

type ConfigValue = boolean | number | string;

export function ModConfigPanel({
  modId,
  modName,
  enabled,
  onToggleEnabled,
  onDirtyChange,
}: {
  modId: string;
  modName: string;
  enabled?: boolean;
  onToggleEnabled?: () => void;
  onDirtyChange?: (modId: string, dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
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
      <Panel>
        <h3 className="font-fraktur text-xl text-parchment mb-3">Config</h3>
        <Fleuron />
        <div className="mt-4 space-y-3 animate-pulse" aria-busy="true">
          <div className="h-10 rounded bg-oxblood/15" />
          <div className="h-10 rounded bg-oxblood/15" />
        </div>
      </Panel>
    );
  }

  if (configQuery.error) {
    return (
      <Panel>
        <h3 className="font-fraktur text-xl text-parchment mb-3">Config</h3>
        <Fleuron />
        <p className="mt-4 text-sm text-ash">{configQuery.error.message}</p>
      </Panel>
    );
  }

  if (!keys.length) {
    return (
      <Panel>
        <h3 className="font-fraktur text-xl text-parchment mb-3">Config</h3>
        <Fleuron />
        <p className="mt-4 text-sm text-ash">
          This mod does not declare any editable config fields.
        </p>
      </Panel>
    );
  }

  return (
    <Panel>
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
    </Panel>
  );
}

function ConfigFieldRow({
  name,
  field,
  value,
  error,
  onChange,
}: {
  name: string;
  field: ModConfigField;
  value: ConfigValue;
  error?: string;
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

      {field.type === 'bool' ? (
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
  if (field.default != null) return field.default;
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
