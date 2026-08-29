---
title: rsmm.sdk.config
description: "Per-mod config: schema validation + persisted store."
---

# rsmm.sdk.config

Per-mod config: schema validation + persisted store.

Schema:
    {fields.<key>.{type, default, min, max, label, choices, enum, source}}

Types: bool, int, float, string, enum, multiselect.

A `multiselect` field holds a LIST of ids. Its options are either spelled out
in `choices`, or fetched from an allowlisted provider named by `source` — see
`rsmm.sdk.config_choices`. A provider supplies a label, a group and an icon per
option, which is what lets the client draw a searchable grid of game art
instead of a wall of internal ids.

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
