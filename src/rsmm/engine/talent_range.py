"""Make a number of an ability bigger while a talent is owned: "+30% POWER radius".

Range is not a stat. Each ability works out its own size in its own entity:
Melusine's POWER radius is ``Primary Ability Radius Operation`` in her caster
entity, ``Primary Ability Default Radius`` (4.0) MULTIPLIED by ``1 + extra``,
where the extra is her Freezing Splash talent's per-rarity number, read from her
hero file through a get-value node (operator ids read off the game's operation
dispatch, ``FUN_14074d880``: 0x17af9527 add, 0x17af9539 subtract, 0x17b29be2
multiply, 0x17b29bec divide). That is the shape written here (``talent_writer``;
until 2026-10-23 copied from Aladdin, Melusine and Carmilla), for any number:

1. **Factor**, in the file holding the talent: a per-rarity selector holding
   ``1 + amount``, read only while the talent's owned state is on ("state
   active -> number, else 1"), behind a plain value node as Melusine's is.
2. **Reader**: when the number lives in another entity of the hero (a caster, a
   projectile), a get-value node reads the factor from the hero's entity, as
   Melusine's caster does.
3. **Scale**: a plain value node ``N`` keeps its name and GUID, so whatever reads
   it still does, and now takes its number from ``N Scaled`` = ``N Base`` (its
   old number) x factor. A multiply operation just gets the factor as one more
   operand. Other operations are refused.

The card gets a ``{N}`` slot showing the amount, as ``add_stat`` does.

PROVEN in game 2026-10-09 (melusine-bigger-power-test 0.4.0): Melusine's POWER
area grew with the talent granted, once the reader was switched on by the
caster's start-up state (``_activate_before``).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from . import entity_graph as EG
from . import entity_graph_edit as GE
from . import entity_parts as P
from . import talent_add_stat as TA
from . import talent_writer as TW

_MUL = 0x17B29BE2


class RangeError(ValueError):
    """The number cannot be scaled this way; the message says why."""


@dataclass(frozen=True)
class Factor:
    name: str          # the value node holding 1 + amount (1 while the talent is not owned)
    selector: str      # the per-rarity amount the card shows
    slot: int | None   # the card's {N} for it


def how_scaled(raw: bytes, node: str) -> str:
    """``"value"`` or ``"multiply"``: how :func:`scale_node` would scale ``node``,
    or :class:`RangeError`."""
    g = EG.parse(raw)
    c = next((c for c in g.components if c.name == node), None)
    if c is None:
        raise RangeError(f"no node {node!r} here")
    if c.cls.endswith("CpntValueSettings"):
        u = next((t for t in EG.tokens(c) if t.kind == "value"), None)
        if u is None or not u.text.startswith("f32"):
            raise RangeError(f"{node!r} does not hold a decimal number")
        return "value"
    if c.cls.endswith("ValueOperationsSettings"):
        toks = EG.tokens(c)
        i = next((i for i, t in enumerate(toks)
                  if t.kind == "object" and t.text == "oCEntityCpntNodeSettings"), None)
        head = bytes.fromhex(toks[i + 1].text.replace(" ", "")) \
            if i is not None and toks[i + 1].kind == "bytes" else b""
        if head[:4] == _MUL.to_bytes(4, "little"):
            return "multiply"
        raise RangeError(f"{node!r} is an operation other than a multiply")
    raise RangeError(f"{node!r} is a {c.cls}, not a number")


def add_factor(raw: bytes, *, talent: str, values, tag: str, percent: bool = True,
               seed: str = "") -> tuple[bytes, Factor]:
    """Return the file holding ``talent`` with a factor node (step 1)."""
    amounts = TA.normalise_values(values)
    graph = EG.parse(raw)
    ctl, state, fmt = TA.card_parts(graph, talent)
    base = f"Skill {talent} Range {tag}"
    show, mult, cond, fac = f"{base} Selector", f"{base} Factor Selector", \
        f"{base} Condition Selector", f"{base} Factor"
    if any(c.name == fac for c in graph.components):
        raise RangeError(f"talent {talent!r} already scales {tag!r}")
    ef = GE.EntityFile(raw)
    w = TW.TalentWriter(ef, f"{seed or talent}:range:{tag}", f"Skill {talent}")
    try:
        card = TW.link_to(ef, ctl.name)
        w.rarity(show, card, amounts)
        one_plus = w.rarity(mult, card, {t: 1.0 + v for t, v in amounts.items()})
        # while the talent is owned 1 + its amount, else 1: no change
        w.value_of(fac, w.when(cond, TW.link_to(ef, state.name), one_plus, 1.0))
        slot = ef.add_format_slot(fmt.name, show, percent=percent) if fmt else None
        return ef.to_bytes(), Factor(fac, show, slot)
    except (GE.EntityEditError, P.PartError) as e:
        raise RangeError(f"talent {talent!r}: {e}") from e


def reader(raw: bytes, *, factor_guid: bytes, factor_label: str, owner_resource: str,
           name: str, seed: str = "", scope: str = "") -> bytes:
    """Return ``raw`` (another entity of the hero) with a node ``name`` reading
    the factor from the hero's entity (step 2). ``factor_label`` is the factor's
    reference label (``[Value] Hero_X\\Group\\Name``) and ``owner_resource`` the
    hero entity's resource path (``Heroes\\Hero_X\\Hero_X.entity.ot``); ``scope`` the
    entity's own name, for one whose references do not tell it."""
    ef = GE.EntityFile(raw, scope)
    try:
        TW.TalentWriter(ef, f"{seed}:get", "").reader(
            name, owner_resource, P.Link(factor_guid, factor_label))
        return ef.to_bytes()
    except (GE.EntityEditError, P.PartError) as e:
        raise RangeError(str(e)) from e


def _activate_before(ef: GE.EntityFile, node: str, new: list[str],
                     first: tuple[str, ...] = ()) -> int:
    """Switch the ``new`` nodes on just before ``node`` wherever a state's
    ``activates`` list switches ``node`` on; returns how many lists took them.

    A spawned entity's nodes do nothing until a state activates them, in order:
    Melusine's caster's ``Event Initialize Power Caster`` switches on her
    Freezing Splash reader, THEN the radius operation, then the attack. A node
    added without that never reads anything (playtest 2026-10-09: the talent
    was granted, the radius did not change). The hero's own file needs none:
    no list there switches the talent's value nodes on."""
    from . import entity_fields as EF
    target = ef.component(node).guid
    lists = 0
    for c in ef.graph().components:
        f = next((x for x in EF.fields(c) if x.name == "activates" and x.kind == "ref[]"), None)
        if f is None:
            continue
        at = next((i for i, it in enumerate(f.items)
                   if c.body[it.offset + 8:it.offset + 24] == target), None)
        if at is None:
            continue
        for k, name in enumerate(new):
            ef.insert_ref(c.name, "activates", at + k, name)
        # A reader of the hero goes first of all: other nodes the list switches
        # on before `node` may read it too (the root node, once its scale does).
        for k, name in enumerate(first):
            ef.insert_ref(c.name, "activates", k, name)
        lists += 1
    return lists


def _scale_defense_traverser(ef: GE.EntityFile, factor: str = "") -> None:
    """Wire Snow Queen's Ability Defense traversers radius picker (slot 16)
    to ``Ability Defense Frost Radius Operation`` so active skating hitbox
    scales with the frost decal."""
    try:
        target = "Ability Defense Frost Radius Operation"
        t = ef.component(target)
        acc = ef.F32_ACCESSOR.get(t.cls)
        if acc is None:
            return
        owned, _ = ef.pointers()
        marker = b"\x11\x11\xbb\xaa\x42\x00\x00\x00"
        union = GE._B + struct.pack("<I", ef._class_index("oCEntityValueUnion"))
        for c_name in ("Ability Defense Traverser", "Ability Defense Traverser Props"):
            c = ef.component(c_name)
            around = [k for k, ptr in owned.items()
                      if ptr.owner == c.index - 1 and ef._class(k) == "oCEntityGpnAroundPositionTraverserSettings"]
            for sid in around:
                p = ef.objects[sid]
                pickers, pos = [], 0
                while True:
                    pos = p.find(marker, pos)
                    if pos == -1: break
                    pickers.append(pos)
                    pos += 1
                if len(pickers) <= 16:
                    continue
                at = pickers[16] + 8
                u = p.find(union, at)
                if u < 0: continue
                p[at:u] = b"\x01\x00" + ef._picker(target) + struct.pack("<I", acc)
                u = p.find(union, at)
                struct.pack_into("<f", p, u + 16, 0.0)
    except (GE.EntityEditError, IndexError, KeyError):
        pass


def scale_node(raw: bytes, *, node: str, factor: str, seed: str = "",
               activate: tuple[str, ...] = (), scope: str = "") -> bytes:
    """Return ``raw`` with ``node`` multiplied by ``factor``, a node of the same
    file (step 3). ``activate`` are nodes added for it (the reader of step 2):
    wherever a state switches ``node`` on, they are switched on first. ``scope``
    is the entity's own name, for one whose references do not tell it (Snow
    Queen's FROST names nothing of its own)."""
    kind = how_scaled(raw, node)
    ef = GE.EntityFile(raw, scope)
    try:
        if kind == "multiply":
            ef.append_operand(node, factor)
            _activate_before(ef, node, [], first=activate)
            if node == "Ability Defense Frost Radius Operation":
                _scale_defense_traverser(ef, factor)
            return ef.to_bytes()
        c = ef.component(node)
        base, scaled = f"{node} Base", f"{node} Scaled"
        if any(x.name in (base, scaled) for x in ef.graph().components):
            raise RangeError(f"{node!r} is already scaled")
        # The base keeps the node's own number: written from its fields, not
        # cloned (cloning lost track of the Beads' FX sub-objects, 2026-10-23).
        w = TW.TalentWriter(ef, f"{seed}:{node}:base", c.group)
        w.add(c.cls, base, P.decode(c), flags=TA._flags_of(ef, node), group=c.group)
        f = ef.component(factor)
        TW.TalentWriter(ef, f"{seed}:{node}:scaled", c.group).multiply(
            scaled, TW.link_to(ef, base), ef.F32_ACCESSOR[c.cls],
            TW.link_to(ef, factor), ef.F32_ACCESSOR[f.cls], group=c.group)
        ef.source_value(node, 0, scaled)
        _activate_before(ef, node, [base, scaled], first=activate)
        return ef.to_bytes()
    except (GE.EntityEditError, P.PartError) as e:
        raise RangeError(f"{node!r}: {e}") from e


#: A 3d node's transform: 11 number slots, position (0-3), rotation (4-7), scale
#: X (8), Y (9, height), Z (10) — read off shipped nodes that drive them from a
#: value: Beowulf's dash warning sets 8 from its attack width and 10 to its
#: length, Merlin's fireball and Melusine's wisp set 8 from a scale operation.
_SCALE_X, _SCALE_Z = 8, 10


def scale_visual(raw: bytes, factor: str, *, scope: str = "") -> tuple[bytes, str | None]:
    """Grow what an entity the hero spawns DRAWS by ``factor``: its root node's
    ground scale (X and Z) reads the factor, so the effects hung on it grow with
    the number ``scale_node`` grew (Melusine's POWER water stayed its old size
    with only the radius scaled, playtest 2026-10-09). Returns the new bytes and
    the root node's name, or ``(raw, None)`` when the entity has no single root
    node with a plain 1 x 1 scale (nothing is guessed). ``scope`` is the entity's
    own name, for one whose references do not tell it."""
    ef = GE.EntityFile(raw, scope)
    roots = []
    for c in ef.graph().components:
        if not c.cls.endswith("3dNodeSettings"):
            continue
        refs = [t for t in EG.tokens(c) if t.kind == "ref"]
        if refs and refs[0].text == "(none)":
            roots.append(c)
    if len(roots) != 1:
        return raw, None
    root = roots[0]
    toks = EG.tokens(root)
    k = next((i for i, t in enumerate(toks)
              if t.kind == "object" and t.text == "oCEntity3dTransformPicker"), None)
    if k is None:
        return raw, None
    vps = [i for i, t in enumerate(toks[k:], k)
           if t.kind == "object" and t.text == "oCEntityCpntValuePicker"][:11]
    for slot in (_SCALE_X, _SCALE_Z):
        if len(vps) <= slot or not toks[vps[slot] + 1].text.startswith("00") \
                or next(t.text for t in toks[vps[slot]:] if t.kind == "value") != "f32 1":
            return raw, None
    try:
        for slot in (_SCALE_X, _SCALE_Z):
            ef.source_value(root.name, slot, factor)
        return ef.to_bytes(), root.name
    except GE.EntityEditError:
        return raw, None


def reads_owner(raw: bytes, owner_resource: str) -> bool:
    """Whether a shipped get-value node of this entity reads ``owner_resource``
    (the hero's entity). Only such entities may read the factor across files: a
    read that finds nothing gives 0, and a radius multiplied by 0 is an ability
    with no area. Every hero has some (Melusine's caster, Piper's projectile,
    Romeo's rose; surveyed 2026-10-09)."""
    return any(c.cls.endswith("GetValueSettings") and owner_resource in "".join(c.literals)
               for c in EG.parse(raw).components)


#: A projectile's range is its speed x how long it flies, so a LIFETIME is a range
#: too: Snow Queen's ATTACK shot flies "Basic Attack Lifetime Duration Default"
#: (0.45 s at speed 25); growing it makes the shot reach further.
_SIZE = re.compile(r"radius|range|length|width|size|scale|distance|area|lifetime", re.I)
_NOT_GAMEPLAY = re.compile(r"fx|camera|mesh|decal|gauge|anim|shader|sound|fmod|\bui\b|preview|"
                           r"smooth|shadow|marker|light|collision|detection|recall|follow", re.I)
#: The ability a node's group names, as the cards name the buttons.
_GROUP_ABILITY = (("Ability Basic", "ATTACK"), ("Ability Primary", "POWER"),
                  ("Ability Secondary", "SPECIAL"), ("Ability Defensive", "DEFENSE"),
                  ("Ability Defense", "DEFENSE"),                 # Snow Queen's spelling
                  ("Ability Wolf Basic", "ATTACK"), ("Ability Wolf Primary", "POWER"),
                  ("Ability Wolf Secondary", "SPECIAL"), ("Ability Wolf Ultimate", "ULTIMATE"),
                  ("Wolf Basic", "ATTACK"), ("Wolf Primary", "POWER"),
                  ("Wolf Secondary", "SPECIAL"), ("Wolf Ultimate", "ULTIMATE"),
                  ("Human Basic", "ATTACK"),
                  ("Ability Trait", "TRAIT"), ("Ability Dash", "DASH"),
                  ("Ability Ultimate", "ULTIMATE"))

RANGE_KINDS = (
    "Melee attack range",
    "Ranged attack range",
    "Circular attack range",
    "Rectangle attack range",
)


def candidates(files: list[tuple[str, bytes]], hero: str) -> list[dict]:
    """``[{file, node, ability, where, value, how}]``: the size numbers (radius,
    length, width ...) of ``hero``'s abilities that :func:`scale_node` can grow
    from a talent in the hero's own file. ``files`` are ``(stem, bytes)`` of the
    hero's entity files; ``ability`` is the button the node's group, else its own
    name, names (``Ability Primary`` / ``Primary ...`` = POWER), or None;
    ``where`` is the spawned entity it is in (a projectile, a caster), or None."""
    main = f"Hero_{hero}"
    owner = f"Heroes\\{main}\\{main}.entity.ot"
    out = []
    for stem, raw in files:
        if stem != main and not reads_owner(raw, owner):
            continue
        for c in EG.parse(raw).components:
            if not _SIZE.search(c.name) or _NOT_GAMEPLAY.search(c.name) \
                    or c.group.startswith("Skill") or _NOT_GAMEPLAY.search(c.group):
                continue
            try:
                how = how_scaled(raw, c.name)
            except RangeError:
                continue
            if how == "value" and c.refs:
                continue                    # read from elsewhere: grow that one instead
            value = next((t.text.split()[1] for t in EG.tokens(c) if t.kind == "value"), "")
            ability = next((a for g, a in _GROUP_ABILITY if c.group.startswith(g)), None) \
                or next((a for g, a in _GROUP_ABILITY if c.name.startswith(g.split()[1] + " ")
                         or c.name.startswith(g)), None)
            if not ability:
                sl = stem.lower()
                nl = c.name.lower()
                if "projectile" in sl or "shot" in sl:
                    ability = "ATTACK"
                elif "power_caster" in sl:
                    ability = "POWER"
                elif "cogsbomb" in sl or "dummy" in sl:
                    ability = "ATTACK"
                elif "ricochet" in sl:
                    ability = "ATTACK"
                elif "rose_aoe" in sl or "rose_explosion" in sl:
                    ability = "POWER" if hero == "Juliet" else "ATTACK"
                elif "wisp" in sl:
                    ability = "TRAIT"
                elif "wolf" in nl:
                    if "basic" in nl: ability = "ATTACK"
                    elif "primary" in nl: ability = "POWER"
                    elif "secondary" in nl: ability = "SPECIAL"
                    elif "ultimate" in nl: ability = "ULTIMATE"
            out.append({"file": stem, "node": c.name, "ability": ability,
                        "where": None if stem == main else stem.removeprefix(main + "_"),
                        "value": None if how == "multiply" else float(value), "how": how})
    return out


def range_modifiers(files: list[tuple[str, bytes]], hero: str) -> list[dict]:
    """Group hero size candidates into the 4 gameplay range modifiers:
    Melee attack range,
    Ranged attack range,
    Circular attack range,
    Rectangle attack range.

    Returns ``[{ability, name, description, nodes: [{file, node}], values_desc}]``.
    """
    cands = candidates(files, hero)
    by_ab: dict[str, list[dict]] = {}
    for c in cands:
        ab = c.get("ability") or "OTHER"
        by_ab.setdefault(ab, []).append(c)

    mods = []
    for ab, items in by_ab.items():
        len_nodes = [x for x in items if re.search(r"length", x["node"], re.I)]
        wid_nodes = [x for x in items if re.search(r"width", x["node"], re.I)]
        proj_nodes = [x for x in items if re.search(r"lifetime|distance", x["node"], re.I)
                      or "projectile" in (x.get("where") or "").lower()
                      or "ricochet" in (x.get("where") or "").lower()]

        # 1. Rectangle: has both length and width (and not an ATTACK with basic/human/wolf melee)
        rect_nodes = []
        if len_nodes and wid_nodes and ab != "ATTACK":
            rect_nodes = len_nodes + wid_nodes
            mods.append({
                "ability": ab,
                "name": "Rectangle attack range",
                "description": "Increases both width and length",
                "nodes": [{"file": n["file"], "node": n["node"]} for n in rect_nodes],
                "values_desc": "Length & width",
            })

        # 2. Melee: ATTACK with length/width/radius (and not projectile only)
        melee = []
        if ab == "ATTACK":
            melee = [x for x in items if (re.search(r"length|width", x["node"], re.I)
                     or re.search(r"radius|range", x["node"], re.I))
                     and not re.search(r"lifetime|projectile", x["node"], re.I)
                     and "projectile" not in (x.get("where") or "").lower()]
            if melee and hero not in ("Piper", "Juliet", "Snow_Queen", "Melusine"):
                mods.append({
                    "ability": ab,
                    "name": "Melee attack range",
                    "description": "Increases melee attack size/radius/reach",
                    "nodes": [{"file": n["file"], "node": n["node"]} for n in melee],
                    "values_desc": "Attack length, width & radius",
                })

        # 3. Ranged: projectile lifetime or distance
        if proj_nodes:
            mods.append({
                "ability": ab,
                "name": "Ranged attack range",
                "description": "Extends projectile range/distance",
                "nodes": [{"file": n["file"], "node": n["node"]} for n in proj_nodes],
                "values_desc": "Projectile range & lifetime",
            })

        # 4. Circular: radius/aoe/explosion (excluding nodes already in rectangle or melee)
        used_nodes = set(n["node"] for n in rect_nodes + proj_nodes + melee)
        circ = [x for x in items if re.search(r"radius|aoe|explosion", x["node"], re.I)
                and x["node"] not in used_nodes]
        if not circ and len_nodes and not wid_nodes and not proj_nodes and ab != "ATTACK":
            circ = [x for x in len_nodes if x["node"] not in used_nodes]
        if circ:
            mults = [x for x in circ if x.get("how") == "multiply"]
            nodes = mults if mults else circ
            mods.append({
                "ability": ab,
                "name": "Circular attack range",
                "description": "Increases AoE radius",
                "nodes": [{"file": n["file"], "node": n["node"]} for n in nodes],
                "values_desc": "AoE radius",
            })

    return mods
