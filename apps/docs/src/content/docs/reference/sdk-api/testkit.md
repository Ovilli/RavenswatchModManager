---
title: rsmm.sdk.testkit
description: Offline testing helpers for mod authors.
---

# rsmm.sdk.testkit

Offline testing helpers for mod authors.

Lets a mod be unit-tested without the game: build a mod in-memory with
:class:`~rsmm.sdk.builder.ModBuilder`, then assert over what it staged via
a small fluent API. Everything reads the builder's accumulated state (the
same data :meth:`ModBuilder.summary` exposes) — no disk writes, no apply,
no Ravenswatch.

    from rsmm import sdk
    from rsmm.sdk.testkit import expect

    def test_my_pack():
        m = sdk.builder.ModBuilder("MyPack", version="1.0.0",
                                   author="me", name="My Pack")
        blade = m.item("FrostBlade", base="VanillaSword", name="Frost Blade")
        m.tag("daggers", [blade])
        m.i18n("EN", {"hello": "Hi"})

        (expect(m)
            .has_item("FrostBlade")
            .has_tag("daggers", "FrostBlade")
            .i18n_complete()
            .clean())            # no validate() warnings

Assertions raise ``AssertionError`` with a readable message and return the
same :class:`ModExpect` so calls chain. Use :func:`conflicts` to check a
set of mods don't collide before shipping a collection.

:::note
Auto-generated from `@sdk_export` registrations by `rsmm docs-gen`. Edit the docstrings in the source module, not this page.
:::

## `testkit`

### `testkit.assert_no_conflicts`

```python
testkit.assert_no_conflicts(*mods: 'ModBuilder') -> 'None'
```

Raise ``AssertionError`` if :func:`conflicts` finds any collision.

### `testkit.conflicts`

```python
testkit.conflicts(*mods: 'ModBuilder') -> 'list[str]'
```

Return human-readable conflict messages across several mods (empty =
safe to ship together). Catches colliding asset overrides, duplicate
``(kind, id)`` content, and duplicate skin-pack keys — the things that
make two mods silently clobber each other at apply time.

### `testkit.expect`

```python
testkit.expect(mod: 'ModBuilder') -> 'ModExpect'
```

Begin a fluent assertion chain over a :class:`ModBuilder`.
