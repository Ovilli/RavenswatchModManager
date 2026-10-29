"""A custom enemy's own AI: its base's variant entity, copied and retuned.

Enemy AI is data (``docs/_re/kinds/enemy-ai.md``). The brain lives in
``NPC_Common``; a family model (``Wolves_Model``) adds the attacks; the variant
an enemy def points at (``Standard_Wolf_Timber``) is a handful of OVERRIDE
records on top: its numbers, and the ``Bhv Fighting State Selector`` whose
entry order is the enemy's attack priority. So a custom AI is a copy of that
variant with two kinds of edit, and nothing above it is touched:

* ``values`` -- a number on any ``Value`` part of the chain. The variant's own
  record is set when it has one; otherwise an override record is added. That
  record names the ORIGINAL part's GUID (the engine merges overrides by it)
  with the path of the nearest entity in the chain that holds the part, the
  shape every shipped override has (Timber's ``Collision Radius`` binds
  Character_Common's GUID through ``Wolves_Model\\Attributes\\...``).
* ``attacks`` -- which of the family's attacks the selector offers, in priority
  order. The entries that are not attacks (leash, U-turn, seek, target lost)
  keep their places; each attack entry is the variant's own first entry with
  its state and condition pickers re-aimed, so the class indices are the
  variant's own.

The copy gets fresh part GUIDs (``prop_cook.restamp_entity_guids``) under the
seed it is given; the ancestors' GUIDs it points at are not its own and stay.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import cooked, corpus
from . import entity_components as ECM
from . import entity_fields as EF
from . import entity_graph as EG
from . import entity_parts as P
from .entity_graph_edit import EntityEditError, EntityFile

_GEN_SUFFIX = ".entity.ot.EntitySettingsResource.gen"
_VALUE = "oCEntityCpntValueSettings"
_SELECTOR = "Bhv Fighting State Selector"
_PICKER = "oCEntityCpntPicker"

#: Friendly names for the AI numbers every NPC_Common enemy reads (defaults
#: are NPC_Common's; a family or variant may override them).
ALIASES: dict[str, str] = {
    "detect_radius": "Wandering Target Detection Radius Default",          # 6
    "alerted_detect_radius": "Wandering Target Detection Radius Alerted",  # 16
    "alert_radius": "Wandering Alert Detection Radius",                    # 9
    "aggro_delay": "Wandering Target Delay Default",                       # 0.5 s
    "alerted_aggro_delay": "Wandering Target Delay Alerted",               # 0.25 s
    "roam_distance": "Wandering Roam Distance",                            # 5
    "chase_radius": "Fighting Target Detection Radius",                    # 30
    "leash": "Fighting Max Leash Distance",                                # 40
    "attack_min": "Fighting Seek Min Attack Distance",                     # 1
    "attack_best": "Fighting Seek Best Attack Distance",                   # 2
    "attack_max": "Fighting Seek Max Attack Distance",                     # 3.5
    "give_up_delay": "Fighting Exit Delay",                                # 3 s
}

#: Keys an ``ai`` table may carry besides the aliases. ``new_attacks`` is built
#: into the family model copy (:func:`add_attacks`), not the variant.
KEYS = frozenset({*ALIASES, "values", "attacks", "new_attacks"})
_ANIMATIC = "oCEntityCpntAnimaticSettings"
_ATTACK_KEYS = frozenset({"name", "from", "animations", "values"})


class EnemyAiError(ValueError):
    pass


def entity_rel(ref: str) -> str:
    """``Enemies\\Wolves\\X.entity.ot`` -> its cooked path under EntitySettings."""
    return "EntitySettings/" + ref.replace("\\", "/").removesuffix(".entity.ot") + _GEN_SUFFIX


def _stem(ref: str) -> str:
    return ref.replace("/", "\\").rsplit("\\", 1)[-1].removesuffix(".entity.ot")


@dataclass
class _Held:
    """A part found up the chain: where (the nearest holder) and whose GUID
    the engine merges on (the original's)."""
    scope: str
    comp: EG.Component
    root_guid: bytes


def _chain(ref: str, read) -> list[tuple[str, EG.EntityGraph]]:
    """The variant's ancestors, nearest first (breadth-first over parents)."""
    out, seen, todo = [], {ref.lower()}, list(ECM.parents(read(entity_rel(ref))))
    while todo:
        r = todo.pop(0)
        if r.lower() in seen:
            continue
        seen.add(r.lower())
        raw = read(entity_rel(r))
        if raw is None:
            raise EnemyAiError(f"ancestor {r} is not in the game files")
        out.append((_stem(r), EG.parse(raw, _stem(r))))
        todo.extend(ECM.parents(raw))
    return out


def _held(chain, name: str, group: str | None = None) -> _Held | None:
    for scope, g in chain:
        hits = [c for c in g.components
                if c.name == name and (group is None or c.group == group)]
        if hits:
            c = hits[0]
            return _Held(scope, c, c.override.guid if c.override else c.guid)
    return None


def _set_value(ef: EntityFile, chain, part: str, value: float, seed: str) -> None:
    own = [c for c in ef.graph().components if c.name == part]
    if own:
        if own[0].cls != _VALUE:
            raise EnemyAiError(f"{part!r} is a {own[0].cls}, not a number")
        ef.set_value(part, "value", value)
        return
    held = _held(chain, part)
    if held is None:
        raise EnemyAiError(f"no part {part!r} in this enemy or anything it inherits "
                           f"(`rsmm entity-graph` lists them)")
    if held.comp.cls != _VALUE:
        raise EnemyAiError(f"{part!r} is a {held.comp.cls}, not a number")
    values = P.decode(held.comp)
    P.PartWriter(ef, seed).add(
        _VALUE, part, values, flags=0x101, group=held.comp.group,
        override=P.Link(held.root_guid, f"[Value] {held.scope}\\{held.comp.group}\\{part}"))
    ef.set_value(part, "value", value)


def _pickers(entry: bytes, picker_ci: int) -> list[tuple[int, int]]:
    """``(start, end)`` of each reference picker inside a selector entry."""
    tag = cooked.MARK_BEGIN + struct.pack("<I", picker_ci)
    out, at = [], entry.find(tag)
    while at >= 0:
        n = struct.unpack_from("<I", entry, at + 24)[0]
        end = at + 28 + n + 4
        out.append((at, end))
        at = entry.find(tag, end)
    return out


def _picker(ci: int, guid: bytes, path: str) -> bytes:
    raw = path.encode("latin-1")
    return (cooked.MARK_BEGIN + struct.pack("<I", ci) + guid
            + struct.pack("<I", len(raw)) + raw + cooked.MARK_END)


def _path_of(entry: bytes, span: tuple[int, int]) -> str:
    a, _ = span
    n = struct.unpack_from("<I", entry, a + 24)[0]
    return entry[a + 28:a + 28 + n].decode("latin-1")


def _is_attack(state_path: str) -> bool:
    # "[State] Wolves_Model\Attack Bite\State Attack Bite" -> group "Attack Bite"
    tail = state_path.split("] ", 1)[-1].split("\\")
    return len(tail) >= 3 and tail[-2].startswith("Attack ")


def available_attacks(chain) -> list[str]:
    """Attack groups the chain offers: a ``State <group>`` + ``<group> Condition``."""
    out = []
    for _scope, g in chain:
        names = {(c.group, c.name) for c in g.components}
        for grp, name in sorted(names):
            if (grp.startswith("Attack ") and name == f"State {grp}"
                    and (grp, f"{grp} Condition") in names and grp not in out):
                out.append(grp)
    return out


def _set_attacks(ef: EntityFile, chain, attacks: list[str]) -> None:
    try:
        sel = ef.component(_SELECTOR)
    except EntityEditError:
        raise EnemyAiError(f"this enemy's own entity has no {_SELECTOR!r} to reorder "
                           f"(its fights are scripted), so 'attacks' cannot apply") from None
    fs = EF.fields(sel)
    entries = [f for f in fs if f.kind == "obj" and f.cls == "oCEntityCpntSelectorEntrySettings"]
    count = next((f for f in fs if f.kind == "bytes" and f.size == 4
                  and f.offset < entries[0].offset), None) if entries else None
    if count is None:
        raise EnemyAiError(f"{_SELECTOR!r} does not have the shipped entry layout")
    ci = ef._class_index(_PICKER)
    blobs = [sel.body[f.offset:f.offset + f.size] for f in entries]
    spans = [_pickers(b, ci) for b in blobs]
    template = next((i for i, s in enumerate(spans) if len(s) >= 2), None)
    if template is None:
        raise EnemyAiError(f"{_SELECTOR!r} has no conditioned entry to copy")

    known = available_attacks(chain)
    built = []
    for name in attacks:
        state = _held(chain, f"State {name}", name)
        cond = _held(chain, f"{name} Condition", name)
        if state is None or cond is None:
            raise EnemyAiError(f"no attack {name!r} in this enemy's family; it has: "
                               f"{', '.join(known) or 'none'}")
        b = blobs[template]
        (s0, s1), (t0, t1) = spans[template][:2]
        sp, tp = _path_of(b, (s0, s1)), _path_of(b, (t0, t1))
        new_s = _picker(ci, state.root_guid,
                        f"{sp.split('] ', 1)[0]}] {state.scope}\\{name}\\State {name}")
        new_t = _picker(ci, cond.root_guid,
                        f"{tp.split('] ', 1)[0]}] {cond.scope}\\{name}\\{name} Condition")
        built.append(b[:s0] + new_s + b[s1:t0] + new_t + b[t1:])

    is_atk = [bool(s) and _is_attack(_path_of(b, s[0])) for b, s in zip(blobs, spans, strict=True)]
    if any(is_atk):
        at = is_atk.index(True)
    else:   # before the first seek entry, else the fallback
        at = next((i for i, (b, s) in enumerate(zip(blobs, spans, strict=True))
                   if s and "Seek Target" in _path_of(b, s[0])), len(blobs) - 1)
    keep = [b for b, a in zip(blobs, is_atk, strict=True) if not a]
    before = sum(1 for a in is_atk[:at] if not a)
    order = keep[:before] + built + keep[before:]

    head = len(ef.objects[sel.index - 1]) - len(sel.body)
    a, b = head + count.offset, head + entries[-1].offset + entries[-1].size
    ef._splice(sel, a, b, struct.pack("<I", len(order)) + b"".join(order))


_CINE_BLOC = "oCActivateEntityCpntCineBloc"
_BLOC_TIME = 4                      # f32 seconds, after the bloc's class index


def anim_duration(path: str, read=None) -> float | None:
    """Length in seconds of the shipped animation at ``path`` (``Characters\\...
    .fbx``), from its cooked clip; None when it is not in the game files."""
    from .cooked_schemas import animation as A
    raw = (read or corpus.read)("3D/" + path.replace("\\", "/") + ".Animation.gen")
    if raw is None:
        return None
    try:
        d = A.parse_payload(b"".join(s.payload for s in cooked.parse(raw).sections)).duration
    except (ValueError, IndexError, struct.error):
        return None
    return d if d > 0 else None


def _retime(ef: EntityFile, c: EG.Component, old: str, new: str) -> None:
    """Scale the timed activations an Animatic owns (its hits, its FX, its
    sounds: `oCActivateEntityCpntCineBloc`, time f32 at +4) by the new clip's
    length over the old one's. They are absolute seconds into the clip, and
    the state exits when the clip ends, so a hit timed past the end of a
    shorter animation never fires: a bear fish slam (1.33 s) on the wolf
    leap's timeline (hit at 1.45 s) hit nothing in game (2026-10-29)."""
    a, b = anim_duration(old), anim_duration(new)
    if not a or not b or abs(a - b) < 1e-3:
        return
    owned, _ = ef.pointers()
    names = [k.name for k in ef.cf.classes]
    for x, p in owned.items():
        sub = ef.objects[x]
        if p.owner != c.index - 1 or names[struct.unpack_from("<I", sub, 0)[0]] != _CINE_BLOC:
            continue
        t = struct.unpack_from("<f", sub, _BLOC_TIME)[0]
        if 0 < t <= a * 1.5:            # a time into this clip, not a stray number
            struct.pack_into("<f", sub, _BLOC_TIME, t * b / a)


def retime_swaps(entity: bytes, stem: str, swaps: dict[str, str]) -> bytes:
    """``entity`` with every Animatic whose FBX ``swaps`` replaces retimed to
    the replacement's length (see `_retime`). Call before the strings change."""
    ef = EntityFile(entity, stem)
    hit = False
    for c in ef.graph().components:
        if c.cls != _ANIMATIC:
            continue
        for s in c.literals:
            if s in swaps and s.lower().endswith(".fbx"):
                _retime(ef, c, s, swaps[s])
                hit = True
    return ef.to_bytes() if hit else entity


def _set_animation(ef: EntityFile, part: str, path: str) -> None:
    """Point the Animatic ``part`` at ``path``: its one FBX string, rewritten in
    that record only (the same animation used elsewhere keeps its own), with
    its timed activations retimed to the new clip's length."""
    c = ef.component(part)
    if c.cls != _ANIMATIC:
        raise EnemyAiError(f"{part!r} is a {c.cls}, not an animation")
    olds = [s for s in c.literals if s.lower().endswith(".fbx")]
    if len(olds) != 1:
        raise EnemyAiError(f"{part!r} names {len(olds)} animations; expected one")
    _retime(ef, c, olds[0], path)
    c = ef.component(part)              # the retime may have rebuilt it
    old = olds[0].encode("latin-1")
    try:
        new = path.encode("ascii")
    except UnicodeEncodeError:
        raise EnemyAiError(f"animation path {path!r} must be ASCII") from None
    rec = ef.objects[c.index - 1]
    lp = struct.pack("<I", len(old)) + old
    if rec.count(lp) != 1:
        raise EnemyAiError(f"{part!r} holds its animation path {rec.count(lp)} times")
    rec[:] = rec.replace(lp, struct.pack("<I", len(new)) + new)


def add_attacks(model: bytes, stem: str, specs: list, *, seed: str) -> tuple[bytes, list[str]]:
    """``model`` with one new attack per spec, and the animations they use.

    A spec ``{name, from, animations?, values?}`` copies the attack group
    ``from`` (``Attack Giant Leap``) as ``name`` (``Attack Belly Slam``): every
    part, with the links among them pointing at the copies, so the copy has
    its own state, condition, cooldown and hit, and shares only what the group
    already reached outside itself (the fighting state, the anim player). Part
    names take ``name`` in place of ``from`` (``State Attack Belly Slam``,
    ``Attack Belly Slam Condition``), which is what makes the copy a selector
    entry `_set_attacks` can place. ``animations`` and ``values`` name the
    SOURCE's parts (``"Attack Giant Leap Anim"``) and are set on the copies."""
    if not isinstance(specs, list) or not all(isinstance(s, dict) for s in specs):
        raise EnemyAiError("new_attacks must be a list of tables")
    ef = EntityFile(model, stem)
    used: list[str] = []
    for n, spec in enumerate(specs, 1):
        bad = set(spec) - _ATTACK_KEYS
        if bad:
            raise EnemyAiError(f"new attack {n} has no key {', '.join(sorted(bad))}; "
                               f"it takes {', '.join(sorted(_ATTACK_KEYS))}")
        name, src = str(spec.get("name") or ""), str(spec.get("from") or "")
        groups = ef.graph().groups()
        if not name.startswith("Attack ") or name in groups:
            raise EnemyAiError(f"new attack {n}: name {name!r} must start with 'Attack ' "
                               f"and not be an existing group")
        if src not in groups or not src.startswith("Attack "):
            have = sorted(g for g in groups if g.startswith("Attack "))
            raise EnemyAiError(f"new attack {name!r}: no attack {src!r} to copy; "
                               f"this family has {', '.join(have)}")
        parts = [c.name for c in groups[src]]
        rename = {p: (p.replace(src, name) if src in p else f"{p} {name}") for p in parts}
        try:
            ef.clone(parts, rename=rename, group={src: name}, seed=f"{seed}:{name}")
        except EntityEditError as e:
            raise EnemyAiError(f"new attack {name!r}: {e}") from e

        def copy_of(part: str, what: str, rename=rename, name=name, src=src) -> str:
            if part not in rename:
                raise EnemyAiError(f"new attack {name!r}: {what} names {part!r}, which is "
                                   f"not a part of {src!r}")
            return rename[part]

        for part, path in (spec.get("animations") or {}).items():
            _set_animation(ef, copy_of(str(part), "animations"), str(path))
            used.append(str(path))
        for part, v in (spec.get("values") or {}).items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise EnemyAiError(f"new attack {name!r}: {part!r} must be a number")
            try:
                ef.set_value(copy_of(str(part), "values"), "value", float(v))
            except EntityEditError as e:
                raise EnemyAiError(f"new attack {name!r}: {e}") from e
    try:
        return ef.to_bytes(), used
    except EntityEditError as e:
        raise EnemyAiError(f"the new attacks do not hold together: {e}") from e


def reskin(leaf: bytes, model_ref: str, swaps: dict[str, str], *,
           read=None) -> tuple[bytes, bytes]:
    """``(leaf, model)``: ``leaf`` now inheriting ``model_ref``, a copy of its
    family model, with ``swaps`` (path -> path: meshes, materials, animations)
    applied to both. Every swap must name a path the two use.

    The copy keeps the model's part GUIDs: the leaf's overrides bind to them
    by GUID, and the spawned entities the model drives (a leap's warning) read
    them too. A custom hero's renamed family keeps its base's GUIDs the same way,
    proven in game. An attack's timing is data on its Animatic (timed
    `oCActivateEntityCpntCineBloc` activations), not in the FBX, so a swapped
    animation still fires the attack at the model's times."""
    from . import entity_strings as ES
    read = read or corpus.read
    ps = ECM.parents(leaf)
    if len(ps) != 1:
        raise EnemyAiError(f"reskin needs one family model to copy; this enemy inherits {ps}")
    old = ps[0]
    model = read(entity_rel(old))
    if model is None:
        raise EnemyAiError(f"{old} is not in the game files")
    in_m = {s for *_, s in ES.list_strings(model)}
    in_l = {s for *_, s in ES.list_strings(leaf)}
    missing = sorted(k for k in swaps if k not in in_m | in_l)
    if missing:
        art = sorted(s for s in in_m | in_l if s.endswith((".fbx", ".mat.ot")))
        raise EnemyAiError(f"reskin: this enemy does not use {', '.join(missing)}; "
                           f"its art is: {', '.join(art)}")
    if swaps:
        model = retime_swaps(model, _stem(old), swaps)
        model = ES.replace_strings(model, {k: v for k, v in swaps.items() if k in in_m})
        leaf = retime_swaps(leaf, _stem(model_ref), swaps)
    leaf = ES.replace_strings(leaf, {old: model_ref,
                                     **{k: v for k, v in swaps.items() if k in in_l}})
    # Links name their target as "[Kind] <scope>\<group>\<name>"; the model's
    # parts now live under the copy's name, as a custom hero's renamed family
    # does. The engine merges by GUID; the label is what the checker and
    # `rsmm entity-graph` read.
    a, b = f"] {_stem(old)}\\", f"] {_stem(model_ref)}\\"

    def rescope(s: str) -> str:
        return s.replace(a, b) if s.startswith("[") else s

    model, _ = ES.rewrite_strings(model, rescope)
    leaf, _ = ES.rewrite_strings(leaf, rescope)
    return leaf, model


def build(base_ref: str, ai: dict, *, seed: str, read=None) -> bytes:
    """The base variant entity ``base_ref`` with ``ai`` applied, re-stamped
    under ``seed`` (the copy's new entity ref)."""
    from .prop_cook import restamp_entity_guids
    read = read or corpus.read
    raw = read(entity_rel(base_ref))
    if raw is None:
        raise EnemyAiError(f"{base_ref} is not in the game files")
    unknown = set(ai) - KEYS
    if unknown:
        raise EnemyAiError(f"ai has no key {', '.join(sorted(unknown))}; it takes "
                           f"{', '.join(sorted(KEYS))}")
    chain = _chain(base_ref, read)
    ef = EntityFile(raw, _stem(base_ref))
    ai = {k: v for k, v in ai.items() if k != "new_attacks"}    # the model's, not ours
    values = {ALIASES[k]: v for k, v in ai.items() if k in ALIASES}
    for part, v in (ai.get("values") or {}).items():
        values[str(part)] = v
    try:
        for part, v in values.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise EnemyAiError(f"{part!r} must be a number, got {v!r}")
            _set_value(ef, chain, part, float(v), f"{seed}:{part}")
        if "attacks" in ai:
            attacks = ai["attacks"]
            if (not isinstance(attacks, list) or not attacks
                    or not all(isinstance(a, str) for a in attacks)):
                raise EnemyAiError("attacks must be a non-empty list of attack names")
            _set_attacks(ef, chain, attacks)
        out = ef.to_bytes()
    except (EntityEditError, P.PartError) as e:
        raise EnemyAiError(str(e)) from e
    return restamp_entity_guids(out, seed)
