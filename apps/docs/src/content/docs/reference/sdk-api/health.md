---
title: rsmm.sdk.health
description: Health system — boot canary + crash-history bisect.
---

# rsmm.sdk.health

Health system — boot canary + crash-history bisect.

Loader writes `<cooking>/.rsmm_boot.json` at DllMain:

    {"started_at": 1716120000, "mods": [...], "last_step": "init"}

Each step transition is `init -> per_mod:A -> per_mod:B -> ready`.
Clean shutdown deletes the file. Crashy boot leaves a stale canary
which we inspect on the next launch.

Crash history lives in `<cooking>/.rsmm_health.json`:

    {
      "version": 1,
      "threshold": 3,
      "mods": {
        "Foo": {"crashes": 2, "last_error": "...", "last_seen": 17161...,
                "disabled_by_health": false}
      }
    }

:::note
Auto-generated from `@sdk_export` registrations by `rsmm docs-gen`. Edit the docstrings in the source module, not this page.
:::

## `Health`

### `Health.disabled_mods`

```python
Health.disabled_mods(self) -> 'set[str]'
```

Ids of mods auto-disabled by the boot-canary crash bisector.

These were quarantined after a crashy launch; the user re-enables
each with :meth:`re_enable` once fixed.

### `Health.re_enable`

```python
Health.re_enable(self, mod_id: 'str') -> 'None'
```

User manually re-enables after fixing the crash.

### `Health.record_crash`

```python
Health.record_crash(self, mod_id: 'str', error: 'str' = '') -> 'HealthState'
```

Bump the mod's crash counter, persist, return the updated state.

If the mod hits `threshold`, mark `disabled_by_health=True`. The
applier consults this on the next run.
