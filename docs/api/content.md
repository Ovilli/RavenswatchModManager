# rsmm.sdk.content

Content kinds registry — façade over per-kind builders.

A mod registers content via `ContentRegistry.register("item", id=..., ...)`
which delegates to the `kinds/<kind>.py` implementation. Each kind owns
its own template + field-patcher + emit step.

Kinds that aren't fully schema-mined yet (bosses, maps, heroes at v3.0)
register their builder but fail with a clear `SchemaNotMined` error on
emit, so authors see exactly which class needs RE work next.

:::note
Auto-generated from `@sdk_export` registrations by `rsmm docs-gen`. Edit the docstrings in the source module, not this page.
:::

## `ContentRegistry`

### `ContentRegistry.register`

```python
ContentRegistry.register(self, kind: 'str', *, id: 'str', schema_version: 'int' = 1, **fields) -> 'ContentRef'
```

Register a content definition of ``kind`` and return its :class:`ContentRef`.

The low-level primitive behind :meth:`Mod.item` / :meth:`Mod.enemy`
/ etc. ``kind`` must be a known builder (``item``, ``enemy``,
``boss``, ``hero``, ``map``, …); non-``confirmed`` kinds require the
mod to opt in with ``experimental=True``. ``id`` must be unique
within the mod for that kind. Extra ``**fields`` are passed to the
kind builder.
