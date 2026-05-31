"""Offline testing helpers for mod authors.

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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .api import sdk_export

if TYPE_CHECKING:  # avoid an import cycle at module load
    from .builder import ModBuilder


class ModExpect:
    """Fluent assertions over a :class:`ModBuilder`'s staged state."""

    def __init__(self, mod: ModBuilder):
        self.mod = mod

    # ---- introspection (non-asserting) --------------------------------

    def ids(self, kind: str | None = None) -> list[str]:
        """Registered content ids, optionally filtered to one ``kind``."""
        return [d.id for d in self.mod._content.defs
                if kind is None or d.kind == kind]

    def field(self, kind: str, id: str) -> dict:
        """The raw (deref'd) fields of one registered def."""
        for d in self.mod._content.defs:
            if d.kind == kind and d.id == id:
                return d.fields
        raise AssertionError(f"no {kind} {id!r} registered in {self.mod.id!r}")

    # ---- content assertions -------------------------------------------

    def has(self, kind: str, id: str) -> ModExpect:
        if id not in self.ids(kind):
            raise AssertionError(
                f"{self.mod.id!r}: expected {kind} {id!r}; have "
                f"{self.ids(kind) or '[]'}")
        return self

    def has_item(self, id: str) -> ModExpect:
        return self.has("item", id)

    def has_enemy(self, id: str) -> ModExpect:
        return self.has("enemy", id)

    def has_boss(self, id: str) -> ModExpect:
        return self.has("boss", id)

    def field_equals(self, kind: str, id: str, key: str, value) -> ModExpect:
        got = self.field(kind, id).get(key)
        if got != value:
            raise AssertionError(
                f"{self.mod.id!r}: {kind} {id!r}.{key} == {got!r}, "
                f"expected {value!r}")
        return self

    # ---- tags ---------------------------------------------------------

    def has_tag(self, tag_id: str, member: str | None = None) -> ModExpect:
        tags = self.mod._tags
        if tag_id not in tags:
            raise AssertionError(
                f"{self.mod.id!r}: no tag {tag_id!r}; have {list(tags) or '[]'}")
        if member is not None and member not in tags[tag_id]:
            raise AssertionError(
                f"{self.mod.id!r}: tag {tag_id!r} missing member {member!r}; "
                f"has {tags[tag_id]}")
        return self

    # ---- skinpacks ----------------------------------------------------

    def has_skinpack(self, name: str) -> ModExpect:
        names = [p["name"] for p in self.mod._skinpacks]
        if name not in names:
            raise AssertionError(
                f"{self.mod.id!r}: no skinpack {name!r}; have {names or '[]'}")
        return self

    # ---- assets -------------------------------------------------------

    def has_asset(self, decoded_path: str) -> ModExpect:
        norm = decoded_path.replace("\\", "/").strip("/")
        if norm not in self.mod._assets:
            raise AssertionError(
                f"{self.mod.id!r}: no asset override for {decoded_path!r}")
        return self

    def asset_count(self, n: int) -> ModExpect:
        got = len(self.mod._assets)
        if got != n:
            raise AssertionError(
                f"{self.mod.id!r}: expected {n} asset override(s), got {got}")
        return self

    # ---- i18n ---------------------------------------------------------

    def i18n_complete(self, locales: list[str] | None = None) -> ModExpect:
        """Assert every key defined in any locale is present in all locales
        (no missing translations). Limit the check to ``locales`` if given."""
        bundles = self.mod._i18n
        present = sorted(bundles) if locales is None else [x.upper() for x in locales]
        all_keys: set[str] = set()
        for loc in present:
            all_keys |= set(bundles.get(loc, {}))
        missing: dict[str, list[str]] = {}
        for loc in present:
            gap = sorted(all_keys - set(bundles.get(loc, {})))
            if gap:
                missing[loc] = gap
        if missing:
            raise AssertionError(
                f"{self.mod.id!r}: incomplete i18n — missing keys {missing}")
        return self

    # ---- whole-mod ----------------------------------------------------

    def clean(self) -> ModExpect:
        """Assert :meth:`ModBuilder.validate` produced no warnings."""
        warns = self.mod.validate()
        if warns:
            raise AssertionError(
                f"{self.mod.id!r}: validate() warnings:\n  - "
                + "\n  - ".join(warns))
        return self


@sdk_export("testkit.expect")
def expect(mod: ModBuilder) -> ModExpect:
    """Begin a fluent assertion chain over a :class:`ModBuilder`."""
    return ModExpect(mod)


@sdk_export("testkit.conflicts")
def conflicts(*mods: ModBuilder) -> list[str]:
    """Return human-readable conflict messages across several mods (empty =
    safe to ship together). Catches colliding asset overrides, duplicate
    ``(kind, id)`` content, and duplicate skin-pack keys — the things that
    make two mods silently clobber each other at apply time."""
    msgs: list[str] = []
    seen_assets: dict[str, str] = {}
    seen_content: dict[tuple[str, str], str] = {}
    seen_keys: dict[int, str] = {}
    for m in mods:
        for path in m._assets:
            if path in seen_assets and seen_assets[path] != m.id:
                msgs.append(
                    f"asset {path!r}: overridden by both {seen_assets[path]!r} "
                    f"and {m.id!r}")
            seen_assets.setdefault(path, m.id)
        for d in m._content.defs:
            key = (d.kind, d.id)
            if key in seen_content and seen_content[key] != m.id:
                msgs.append(
                    f"{d.kind} {d.id!r}: defined by both "
                    f"{seen_content[key]!r} and {m.id!r}")
            seen_content.setdefault(key, m.id)
        for p in m._skinpacks:
            k = p["key"]
            if k in seen_keys and seen_keys[k] != m.id:
                msgs.append(
                    f"skinpack key {k}: used by both {seen_keys[k]!r} "
                    f"and {m.id!r}")
            seen_keys.setdefault(k, m.id)
    return msgs


@sdk_export("testkit.assert_no_conflicts")
def assert_no_conflicts(*mods: ModBuilder) -> None:
    """Raise ``AssertionError`` if :func:`conflicts` finds any collision."""
    msgs = conflicts(*mods)
    if msgs:
        raise AssertionError("mod conflicts:\n  - " + "\n  - ".join(msgs))
