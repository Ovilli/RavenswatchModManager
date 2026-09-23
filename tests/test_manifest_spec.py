"""`rsmm.sdk.manifest_spec` must match what the kinds actually read.

The spec is a hand-kept list, and a hand-kept list drifts. Both directions are
checked against the kind modules' source: a key a kind reads but the spec does
not list would be REJECTED by the registry (breaking a working mod), and a key
the spec lists but no kind reads is exactly the silent no-op the spec exists
to catch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rsmm.sdk import content as C
from rsmm.sdk import manifest_spec as S

_KINDS_DIR = Path(C.__file__).parent / "kinds"

#: Where each kind's field reads live. `item` delegates part of its parse to
#: the `item/` package's legacy manifest builder.
_EXTRA_SOURCES = {"item": [_KINDS_DIR / "item" / "builder.py"]}

#: A read of a top-level field: `defn.fields.get("x")`, `fields["x"]`,
#: `f.get("x")` (poi aliases `f = defn.fields`), `"x" in defn.fields`.
_READ = re.compile(
    r"""(?:\bdefn\.fields|\bfields|\bf)\s*(?:\.(?:get|pop)\(\s*|\[\s*)"([a-z_]+)"|"""
    r""""([a-z_]+)"\s+in\s+(?:defn\.fields|fields|f)\b""")


def _sources(kind: str) -> list[Path]:
    mod = C._KIND_MODULES.get(kind, f"{kind}s")
    return [_KINDS_DIR / f"{mod}.py", *_EXTRA_SOURCES.get(kind, [])]


def _source_text(kind: str) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _sources(kind))


def test_spec_covers_every_kind():
    assert set(S.CONTENT_FIELDS) == set(C.KINDS)


@pytest.mark.parametrize("kind", sorted(S.CONTENT_FIELDS))
def test_every_field_a_kind_reads_is_declared(kind):
    reads = {a or b for a, b in _READ.findall(_source_text(kind))}
    undeclared = reads - S.content_fields(kind)
    assert not undeclared, (
        f"{kind} reads {sorted(undeclared)} but manifest_spec.CONTENT_FIELDS"
        f"[{kind!r}] does not list them — the registry would reject them")


@pytest.mark.parametrize("kind", sorted(S.CONTENT_FIELDS))
def test_every_declared_field_is_read_by_its_kind(kind):
    text = _source_text(kind)
    unread = {k for k in S.CONTENT_FIELDS[kind] if f'"{k}"' not in text}
    assert not unread, (
        f"manifest_spec declares {sorted(unread)} for {kind}, but the kind never "
        f"reads them — a field nothing reads is a silent no-op")


def test_kind_own_field_lists_agree_with_the_spec():
    """Kinds that already enforce their own list must not accept a key the
    registry rejects (or the other way round)."""
    from rsmm.sdk.kinds import bosses, enemies, items, shops
    assert set(enemies._CLONE_FIELDS) | set(enemies._OVERRIDE_FIELDS) \
        <= S.CONTENT_FIELDS["enemy"]
    assert set(items._BAN_FIELDS) <= S.CONTENT_FIELDS["item"]
    assert set(bosses._FIELDS) <= S.CONTENT_FIELDS["boss"]
    assert set(shops._FIELDS) <= S.CONTENT_FIELDS["shop"]


def test_registry_rejects_an_unknown_field_with_a_suggestion():
    cr = C.ContentRegistry(mod_id="M", experimental=True)
    with pytest.raises(C.ContentError, match=r"unknown field\(s\) colour"):
        cr.register("enemy", id="X", base="Crab", colour="red")
    with pytest.raises(C.ContentError, match=r"valeu_patches \(did you mean 'value_patches'\?\)"):
        cr.register("item", id="Y", base="Z", valeu_patches=[])


def test_registry_accepts_every_declared_field():
    cr = C.ContentRegistry(mod_id="M", experimental=True)
    for kind, fields in S.CONTENT_FIELDS.items():
        cr.register(kind, id=f"{kind}_all", **{k: None for k in fields})


def test_unknown_keys_suggests_the_nearest_name():
    assert S.unknown_keys({"valeu", "name"}, {"name", "value"}) == [("valeu", "value")]
    assert S.unknown_keys({"zzz"}, {"name"}) == [("zzz", None)]


def test_json_schema_has_a_branch_per_kind_and_patch():
    sch = S.json_schema()
    content = sch["properties"]["content"]["items"]
    assert sorted(content["properties"]["kind"]["enum"]) == sorted(C.KINDS)
    assert len(content["allOf"]) == len(C.KINDS)
    for br in content["allOf"]:
        assert br["then"]["additionalProperties"] is False
    patch = sch["properties"]["patch"]["items"]
    assert sorted(patch["properties"]["kind"]["enum"]) == sorted(S.PATCH_FIELDS)
    assert set(sch["properties"]["mod"]["properties"]) == set(S.MOD_FIELDS)
