# rsmm.sdk.health

Health system — boot canary + crash history, as written by the LOADER.

The loader is the only process that can observe a crashy boot, so it owns the
file. `src/loader/src/health.cpp` opens `<game>/mods/_health.json` before any
mod code runs, stamps `canary.step` as each `init.lua` executes, and closes the
canary ~2 s after `ready`. A canary still open at the next launch means the
previous run died at that step, so the crash is attributed to that mod; three
consecutive failed boots disable it.

    {
      "version": 1,
      "canary": {"open": false, "step": "boot_ok", "session": "fd1d"},
      "mods": {
        "Foo": {"crashes": 2, "last_error": "...",
                "disabled": false, "disabled_reason": ""}
      }
    }

This module is the read/write side for the CLI. It used to describe — and
address — a completely different pair of files: `.rsmm_boot.json` and
`.rsmm_health.json` under `_Cooking`, with `last_step` instead of
`canary.step` and `disabled_by_health` instead of `disabled`. Nothing has ever
written those, so every consumer silently no-opped: `rsmm doctor` reported "no
crash records" while the loader had a mod disabled, `apply`'s quarantine pass
never quarantined anything, and `safe-mode --bisect` wrote its findings where
the loader would never read them. Two health systems that never met.

Writes are read-modify-write on the whole document so the CLI can never clobber
the canary node the loader is keeping, and land via temp-file + rename — the
whole point of this file is to survive a process that dies at an arbitrary
instant, so it must never be observed truncated.

:::note
Auto-generated from `@sdk_export` registrations by `rsmm docs-gen`. Edit the docstrings in the source module, not this page.
:::

## `Health`

### `Health.disabled_mods`

```python
Health.disabled_mods(self) -> 'set[str]'
```

Ids of mods the loader (or a bisect) has quarantined.

These were disabled after a crashy launch; the user re-enables each
with :meth:`re_enable` once fixed.

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

At `threshold` the mod is marked disabled, which the loader honours at
load and the applier honours at apply.
