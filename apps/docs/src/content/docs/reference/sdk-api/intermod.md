---
title: rsmm.sdk.intermod
description: Inter-mod API registry — Python-host mirror of the Lua-side R.api.
---

# rsmm.sdk.intermod

Inter-mod API registry — Python-host mirror of the Lua-side R.api.

A mod exposes a table of callables via `expose(mod_id, table, version)`.
Another mod consumes it via `require(name, version_spec)` and gets a
proxy that:

  * `try/except`s every call so a producer crash can't bring down the
    consumer (errors are logged + re-raised as `InterModError`),
  * semver-checks once at require-time,
  * is read-only — no attribute mutation through the proxy.

This is the authoritative Python implementation. The Lua side mirrors
the same shape for in-process mods; host-side scripts (Python mods,
tests) use this module directly.

:::note
Auto-generated from `@sdk_export` registrations by `rsmm docs-gen`. Edit the docstrings in the source module, not this page.
:::

## `InterModRegistry`

### `InterModRegistry.expose`

```python
InterModRegistry.expose(self, mod_id: 'str', table: 'dict[str, Callable]', version: 'str' = '0.0.0', *, api_name: 'str | None' = None) -> 'None'
```

Publish a table under `api_name` (defaults to `mod_id`).

### `InterModRegistry.require`

```python
InterModRegistry.require(self, name: 'str', version_spec: 'str' = '') -> 'InterModProxy'
```

Resolve another mod's published API by name (Forge-style inter-mod call).

Returns a proxy exposing the provider's exported callables. Raises
``InterModError`` if no mod published ``name``, or if its version
does not satisfy ``version_spec`` (e.g. ``">=1.2"``).
