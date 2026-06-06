---
title: rsmm.sdk.testkit
---

# rsmm.sdk.testkit

## `testkit.assert_no_conflicts(*mods: 'ModBuilder') -> 'None'`

Raise ``AssertionError`` if :func:`conflicts` finds any collision.

## `testkit.conflicts(*mods: 'ModBuilder') -> 'list[str]'`

Return human-readable conflict messages across several mods (empty =
safe to ship together). Catches colliding asset overrides, duplicate
``(kind, id)`` content, and duplicate skin-pack keys — the things that
make two mods silently clobber each other at apply time.

## `testkit.expect(mod: 'ModBuilder') -> 'ModExpect'`

Begin a fluent assertion chain over a :class:`ModBuilder`.
