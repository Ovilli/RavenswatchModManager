"""An enemy, summoned as an ally: a copy of a shipped enemy that fights for the
heroes (Blood Wolf's wolf). Static RE, Ravenswatch b9c3 (2026-11-01).

Who a creature fights is data, in two places:

* its BASE: enemies inherit ``Enemy_Model``, summons ``Ally_Model`` (Sun
  Wukong's AI clone, Kintaro's bear). ``Ally_Model`` sets the ally flag and
  overrides ``NPC_Common``'s target search to look for enemies.
* its ATTACKS: every attack's Gpn traverser owns a ``Gpn Flag Mask Tester``
  whose inline ``oCGpnFilter`` names the side it hits. The filter is
  ``u32 layer``, list A (count + tri-states), list B (count + tri-states);
  compiled by FUN_140703410 and tested by FUN_140838b50 against the target's
  flag bits: list B must ALL match, list A must match ANY; 1 = set, 0 = clear,
  2 = either. The bits are ``Character_Common`` "GPN Default"'s custom flags in
  order: Ally, Neutral, Enemy, (4th). Heroes are Ally. A wolf's bite hits
  ANY[Ally, Neutral]; the monkey clone's hits ANY[Neutral, Enemy].

So an ally copy is: the enemy's model layer re-parented from ``Enemy_Model``
to ``Ally_Model`` (its links "into Enemy_Model" carry the identities of the
shared parts Enemy_Model overrode, so they resolve on the ally base as well),
and every attack filter mirrored (Ally and Enemy swapped, the hero layer for
the layer allies target).
"""

from __future__ import annotations

import struct

from . import cooked, corpus
from . import entity_components as EC

ENEMY_MODEL = "Enemies\\NPC_Common\\Enemy_Model.entity.ot"
ALLY_MODEL = "Enemies\\NPC_Common\\Ally_Model.entity.ot"
#: Piper's rats' base, on Ally_Model: follows its master and obeys the master's
#: named-event orders (PET_MASTER_ATTACK_MOVE_ORDER / _RECALL_ORDER / _TELEPORT).
PET_MODEL = "Heroes\\Hero_Pets\\Hero_Pet_Model.entity.ot"
#: Gpn layers a filter names: heroes, and what allies target (Ally_Model's
#: "Fighting Target Traverser"; NPC_Common's enemy one uses the hero layer).
HERO_LAYER, ALLY_TARGET_LAYER = 0x1724391E, 0x0F9E2000
#: Positions of the side flags in a filter's lists.
ALLY, ENEMY = 0, 2

class SummonError(ValueError):
    pass


def _rel(ref: str) -> str:
    return "EntitySettings/" + ref.replace("\\", "/") + ".EntitySettingsResource.gen"


def _read(ref: str) -> bytes:
    raw = corpus.read(_rel(ref))
    if raw is None:
        raise SummonError(f"{ref} is not in the game files")
    return raw


def flip_side(raw: bytes, only: set[int] | None = None) -> tuple[bytes, int]:
    """``raw`` with every attack and search filter it owns mirrored: Ally and
    Enemy swapped in both lists, the hero layer swapped for the one allies
    target. Returns the bytes and how many filters.

    Two places hold them (Ghidra + corpus, 2026-11-03): a flag mask tester's
    inline ``oCGpnFilter``, and a GPN traverser's, which ALSO names the layer
    it queries after its last object (MARK_END x3 + u32). The wolf's in-range
    checks ("Attack Bite No Root Motion Traverser") filter nothing and query
    the hero layer: flipping testers alone left them seeing only heroes, so an
    ally wolf stood next to enemies and never attacked. ``only``: the section
    indexes to flip (an override added after the copy's own flip)."""
    cf = cooked.parse(raw)
    names = [c.name for c in cf.classes]
    owners = {names.index(c) for c in ("oCEntityGpnFlagMaskTesterSettings",
                                       "oCEntityCpntGpnTraverserSettings") if c in names}
    if not owners or "oCGpnFilter" not in names:
        return raw, 0
    filt = struct.pack("<I", names.index("oCGpnFilter"))
    swap = {HERO_LAYER: ALLY_TARGET_LAYER, ALLY_TARGET_LAYER: HERO_LAYER}
    tail = cooked.MARK_END * 3
    n = 0
    for k, sec in enumerate(cf.sections):
        p = bytearray(sec.payload)
        if len(p) < 4 or struct.unpack_from("<I", p, 0)[0] not in owners:
            continue
        if only is not None and k not in only:
            continue
        j = p.find(cooked.MARK_BEGIN + filt)
        if j < 0:
            raise SummonError("a flag mask tester or traverser holds no filter where expected")
        while j >= 0:
            o = j + len(cooked.MARK_BEGIN) + 4
            layer = struct.unpack_from("<I", p, o)[0]
            if layer in swap:
                struct.pack_into("<I", p, o, swap[layer])
            o += 4
            for _ in range(2):                                   # list A, list B
                count = struct.unpack_from("<I", p, o)[0]
                if count > 32:
                    raise SummonError(f"a filter list claims {count} flags; not a filter")
                vals = list(struct.unpack_from(f"<{count}I", p, o + 4))
                if any(v != 2 for v in vals):
                    # A short list (the wolf's "in range" check is just [Ally])
                    # grows with "either" entries so Enemy has a place to swap to.
                    vals += [2] * (ENEMY + 1 - len(vals))
                    vals[ALLY], vals[ENEMY] = vals[ENEMY], vals[ALLY]
                    p[o:o + 4 + 4 * count] = struct.pack(f"<I{len(vals)}I", len(vals), *vals)
                o += 4 + 4 * len(vals)
            n += 1
            j = p.find(cooked.MARK_BEGIN + filt, o)
        # A traverser's query layer, after its last object.
        t = p.rfind(tail)
        if t >= 0 and t + len(tail) + 4 <= len(p):
            q = t + len(tail)
            layer = struct.unpack_from("<I", p, q)[0]
            if layer in swap:
                struct.pack_into("<I", p, q, swap[layer])
        sec.payload = bytes(p)
    return cooked.emit(cf), n


def _check_no_enemy_only_links(raw: bytes, stem: str) -> None:
    """Refuse a copy that links a part only Enemy_Model has. Its links into
    Enemy_Model's OVERRIDES already carry the shared part's identity (the
    wolf's mesh scale is Character_Common's, its leash state NPC_Common's), so
    on Ally_Model they resolve; a part of Enemy_Model's own would not."""
    from .entity_graph_edit import EntityFile
    own = {c.guid: c.name for c in EntityFile(_read(ENEMY_MODEL), "Enemy_Model").graph().components
           if c.override is None}
    for c in EntityFile(raw, stem).graph().components:
        for r in c.refs:
            if r.guid in own:
                raise SummonError(f"{stem}'s {c.name!r} links {own[r.guid]!r}, which only "
                                  "Enemy_Model has; an ally copy would lose it")


def build(variant: str, model_ref: str, variant_ref: str, seed: str,
          base: str = ALLY_MODEL) -> dict[str, bytes]:
    """An ally copy of enemy ``variant`` (``Enemies\\Wolves\\Standard_Wolf_Timber
    .entity.ot``): its model layer copied to ``model_ref`` on ``base``
    (Ally_Model: a summon, as Sun Wukong's clone; PET_MODEL: a pet), the
    variant to ``variant_ref`` inheriting that copy. Both carry identities of
    their own under ONE mapping (the variant overrides the model's parts by
    identity). Returns ``{ref: bytes}``."""
    from . import hero_cook as H
    v_raw = _read(variant)
    models = [p for p in EC.parents(v_raw) if p != ENEMY_MODEL]
    if len(models) != 1:
        raise SummonError(f"{variant}: expected one model layer, found {models or 'none'}")
    model = models[0]
    m_raw = _read(model)
    if ENEMY_MODEL not in EC.parents(m_raw):
        raise SummonError(f"{model} does not inherit Enemy_Model; not a summonable enemy")
    m_stem = model_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    v_stem = variant_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")

    _check_no_enemy_only_links(m_raw, m_stem)
    _check_no_enemy_only_links(v_raw, v_stem)
    m_out, n_m = flip_side(EC.replace_parent(m_raw, ENEMY_MODEL, base))
    v_out, _n_v = flip_side(EC.replace_parent(v_raw, model, model_ref))
    if not n_m:
        raise SummonError(f"{model} has no attack filters to turn; it would still hit heroes")
    mapping = H.family_guid_map([m_raw, v_raw], seed)
    return {model_ref: H.apply_guid_map(m_out, mapping),
            variant_ref: H.apply_guid_map(v_out, mapping)}
