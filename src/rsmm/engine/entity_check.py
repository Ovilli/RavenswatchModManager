"""Static checks on an edited entity file, run before it is applied.

The shipped game is not a clean baseline. Across its 4700 entity files, 183
references resolve to no component anywhere and ~8000 bind into an entity that
is neither the file itself nor one of its ancestors (a camp reading
``NPC_Common``'s leash distance, a hero reading its own spawned rats). The
engine lives with all of that. So a check that flagged every such reference
would flag the game itself, and a check that flagged none would pass exactly
the mistakes an editor makes.

The checks therefore judge the EDIT: they compare the edited bytes with the
file they started from, and only what the edit introduced is held to the
rules. Everything here is static; it proves a file is well-formed and wired to
things that exist, not that the ability plays the way its author meant.

Errors (``Issue.error``) block an apply:

* structure: object table, component vector, class indexes, unique GUIDs;
* a sub-object the edit left without an owner, or with two;
* a new reference to a component that exists nowhere;
* a new reference into an entity this one does not inherit, when that entity
  is one other entities inherit from. That is how a component copied from
  Juliet keeps links into ``Hero_Romeo_Juliet_Common``, which Piper does not
  carry: the links bind to nothing and the copy does nothing;
* a resource the edit introduced that the entity's preload cache does not
  list. A resource the cache never listed resolves to null, and the engine's
  teardown destroys it unchecked (see rsc_cache).

Warnings are reported and do not block:

* a new reference into a standalone entity (a pet, a projectile, a zone):
  shipped heroes do this, and it binds only while that entity exists.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

from . import cooked, rsc_cache
from . import entity_graph as EG
from . import entity_strings as ES
from .entity_edit import EntityEditError, EntityFile

#: entity reference (``Heroes\\Hero_Piper\\Hero_Piper_FX.entity.ot``) -> bytes
Reader = Callable[[str], bytes | None]


@dataclass
class Issue:
    error: bool
    where: str          # component, or "" for the file
    message: str

    def __str__(self) -> str:
        tag = "error" if self.error else "warning"
        return f"[{tag}] {self.where + ': ' if self.where else ''}{self.message}"


def entity_rel(ref: str) -> str:
    """Corpus path of an entity reference."""
    return "EntitySettings/" + ref.replace("\\", "/") + ".EntitySettingsResource.gen"


def _corpus_reader(ref: str) -> bytes | None:
    from . import corpus
    return corpus.read(entity_rel(ref))


def check(edited: bytes, original: bytes | None, *, name: str = "",
          read: Reader | None = None, cache_text: bytes | None = None,
          cache_ref: str | None = None) -> list[Issue]:
    """Issues the edit from ``original`` to ``edited`` introduced.

    ``read`` resolves an entity reference to bytes (default: the shipped
    corpus); pass one that also knows a mod's own entities. ``cache_text`` is
    the entity's preload cache; when omitted it is read beside ``cache_ref``
    (the entity's own reference) from the corpus, and when there is none the
    resource check is skipped."""
    read = read or _corpus_reader
    issues: list[Issue] = []
    try:
        ef = EntityFile(edited, name)
        ef.to_bytes()
    except (ValueError, EntityEditError) as e:
        return [Issue(True, "", f"file does not hold together: {e}")]
    issues += _class_tags(ef)
    g = ef.graph()
    before = EG.parse(original) if original else EG.EntityGraph(name, [])
    issues += _ownership(ef, EntityFile(original, name) if original else None)
    issues += _references(ef, g, before, read)
    issues += _resources(edited, original, read, cache_text, cache_ref)
    return issues


# ---- structure --------------------------------------------------------------

def _class_tags(ef: EntityFile) -> list[Issue]:
    n = len(ef.cf.classes)
    bad = []
    for i, p in enumerate(ef.objects + [ef.trailer]):
        at = p.find(cooked.MARK_BEGIN)
        while at >= 0:
            if at + 8 <= len(p) and struct.unpack_from("<I", p, at + 4)[0] >= n:
                bad.append(i)
                break
            at = p.find(cooked.MARK_BEGIN, at + 1)
    return [Issue(True, "", f"object #{i} names a class outside the class table")
            for i in bad]


def _ownership(ef: EntityFile, before: EntityFile | None) -> list[Issue]:
    owned, ambiguous = ef.pointers()
    was = set(before.pointers()[1]) if before else set()
    out = []
    for x, cands in ambiguous.items():
        if x in was:
            continue
        what = f"sub-object #{x} ({ef._class(x)})"
        if not cands:
            out.append(Issue(True, "", f"{what} is owned by nothing"))
        else:
            out.append(Issue(True, "", f"{what} has {len(cands)} possible owners"))
    return out


# ---- references ---------------------------------------------------------------

def _ancestors(data: bytes, read: Reader) -> dict[bytes, str]:
    """GUID -> entity stem, for every component this entity inherits."""
    from .entity_components import parents
    out: dict[bytes, str] = {}
    seen: set[str] = set()
    todo = list(parents(data))
    while todo:
        ref = todo.pop()
        if ref in seen:
            continue
        seen.add(ref)
        raw = read(ref)
        if raw is None:
            continue
        stem = ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
        for c in EG.parse(raw).components:
            out.setdefault(c.guid, stem)
        todo += parents(raw)
    return out


def _references(ef: EntityFile, g: EG.EntityGraph, before: EG.EntityGraph,
                read: Reader) -> list[Issue]:
    old = {(c.guid, r.guid) for c in before.components for r in c.refs}
    old |= {(c.guid, c.override.guid) for c in before.components if c.override}
    own = g.by_guid()
    inherited: dict[bytes, str] | None = None
    reached: set[str] | None = None
    out = []
    for c in g.components:
        links = list(c.refs) + ([c.override] if c.override else [])
        for r in links:
            if (c.guid, r.guid) in old or r.guid in own:
                continue
            if inherited is None:
                inherited = _ancestors(ef.to_bytes(), read)
                # Entities the original already binds into are available to it,
                # whatever the mechanism: a hero reaches Hero_Common and
                # Character_Common without naming them as parents.
                reached = {h for c0 in before.components for r0 in c0.refs
                           for h in _guid_index().get(r0.guid, ())}
            if r.guid in inherited:
                continue
            homes = _guid_index().get(r.guid, frozenset())
            if homes & reached:
                continue
            home = _entity_of(r)
            if home is None:
                out.append(Issue(True, c.name, f"links to {r.path}, which exists nowhere"))
            elif home in _inherited_entities():
                out.append(Issue(True, c.name,
                    f"links to {r.path} in {home}, which other entities inherit but this "
                    f"one does not: the link binds to nothing. Copy those components too, "
                    f"or re-point the link"))
            else:
                out.append(Issue(False, c.name,
                    f"links into {home} ({r.path}); that binds only while {home} exists"))
    return out


def _entity_of(r: EG.Ref) -> str | None:
    """The shipped entity holding the component ``r`` targets: preferably the
    one its path's scope names, else any."""
    homes = _guid_index().get(r.guid)
    if not homes:
        return None
    return r.scope if r.scope in homes else sorted(homes)[0]


@cache
def _guid_index() -> dict[bytes, frozenset[str]]:
    """Component GUID -> stems of the shipped entities that hold it."""
    from . import corpus
    idx: dict[bytes, set[str]] = {}
    for rel in corpus.rels("EntitySettings/"):
        if rel.endswith(".EntitySettingsResource.gen"):
            stem = rel.rsplit("/", 1)[-1].removesuffix(".entity.ot.EntitySettingsResource.gen")
            for c in EG.parse(corpus.read(rel)).components:
                idx.setdefault(c.guid, set()).add(stem)
    return {k: frozenset(v) for k, v in idx.items()}


@cache
def _inherited_entities() -> frozenset[str]:
    """Stems of every shipped entity some other entity names as a parent."""
    from . import corpus
    from .entity_components import parents
    out: set[str] = set()
    for rel in corpus.rels("EntitySettings/"):
        if rel.endswith(".EntitySettingsResource.gen"):
            for ref in parents(corpus.read(rel)):
                out.add(ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot"))
    return frozenset(out)


# ---- resources ------------------------------------------------------------------

def resource_paths(data: bytes) -> set[str]:
    """Resource paths the file names through a weak reference (the
    ``oCResourceWeakRef`` pair: archive, path)."""
    cf = cooked.parse(data)
    names = [c.name for c in cf.classes]
    if "oCResourceWeakRef" not in names:
        return set()
    tag = cooked.MARK_BEGIN + struct.pack("<I", names.index("oCResourceWeakRef"))
    out: set[str] = set()
    for sec in cf.sections:
        p = sec.payload
        i = p.find(tag)
        while i >= 0:
            strs = [s for _o, s in ES._scan_payload(p[i + 8:p.find(cooked.MARK_END, i)])]
            if len(strs) >= 2 and strs[1]:
                out.add(strs[1])
            i = p.find(tag, i + 1)
    return out


def _resources(edited: bytes, original: bytes | None, read: Reader,
               cache_text: bytes | None, cache_ref: str | None) -> list[Issue]:
    new = resource_paths(edited) - (resource_paths(original) if original else set())
    if not new:
        return []
    if cache_text is not None:
        caches = {"the given cache": _lines(cache_text)}
    elif cache_ref:
        # The caches that preload this entity must preload what it now names:
        # a hero's are its herodef's and the versiondef's, not its own.
        caches = {k: v for k, v in _cache_index().items() if cache_ref in v}
    else:
        caches = {}
    if not caches:
        return [Issue(False, "", f"{len(new)} new resource(s) and no preload cache to "
                                 f"check them against: {', '.join(sorted(new)[:5])}")]
    return [Issue(True, "", f"{p} is not in {where} (it would load as null)")
            for where, listed in sorted(caches.items()) for p in sorted(new - listed)]


def _lines(text: bytes) -> set[str]:
    return {ln.split("|")[1] for ln in rsc_cache.parse(text) if ln.count("|") == 2}


@cache
def _cache_index() -> dict[str, frozenset[str]]:
    """Every shipped preload cache -> the resource paths it lists."""
    from . import corpus
    out = {}
    # Caches are read by name, never listed (they are absent from asset_map,
    # so a player's install cannot enumerate them): derive each candidate from
    # the definition or entity it belongs to.
    for rel in corpus.rels("Definitions/") + corpus.rels("EntitySettings/"):
        try:
            path = rsc_cache.cache_path_for(rel)
        except rsc_cache.CacheError:
            continue
        raw = corpus.read(path)
        if raw is not None:
            out[path] = frozenset(_lines(raw))
    return out


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.error]
