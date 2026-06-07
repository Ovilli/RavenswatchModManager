# rsmm.sdk.config

Per-mod config: schema validation + persisted store.

Schema:
    {fields.<key>.{type, default, min, max, label, choices, enum}}

Types: bool, int, float, string, enum.

Storage:
    mods/<id>/config.toml  — user-edited values
    mods/<id>/config_schema.toml  — schema (authored by modder)

:::note
Auto-generated from `@sdk_export` registrations by `rsmm docs-gen`. Edit the docstrings in the source module, not this page.
:::

## `ConfigStore`

### `ConfigStore.get`

```python
ConfigStore.get(self, key: 'str', fallback: 'Any' = None) -> 'Any'
```

Read a config value by key, returning ``fallback`` if unset.

### `ConfigStore.set`

```python
ConfigStore.set(self, key: 'str', value: 'Any') -> 'None'
```

Set a config value, coercing to the schema field's type and persisting.

Raises ``ConfigError`` if ``key`` is not declared in the schema.
