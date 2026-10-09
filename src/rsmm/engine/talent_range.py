"""Make a number of an ability bigger while a talent is owned: "+30% POWER radius".

Range is not a stat. Each ability works out its own size in its own entity:
Melusine's POWER radius is ``Primary Ability Radius Operation`` in her caster
entity, ``Primary Ability Default Radius`` (4.0) MULTIPLIED by ``1 + extra``,
where the extra is her Freezing Splash talent's per-rarity number, read from her
hero file through a get-value node (operator ids read off the game's operation
dispatch, ``FUN_14074d880``: 0x17af9527 add, 0x17af9539 subtract, 0x17b29be2
multiply, 0x17b29bec divide). That is the shape copied here, for any number:

1. **Factor**, in the file holding the talent: a per-rarity selector holding
   ``1 + amount``, read only while the talent's owned state is on (a copy of
   Aladdin's "state active -> number, else" selector, whose else is set to 1),
   behind a plain value node as Melusine's is.
2. **Reader**: when the number lives in another entity of the hero (a caster, a
   projectile), a copy of Melusine's caster's get-value node reads the factor
   from the hero's entity.
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
from dataclasses import dataclass

from . import entity_graph as EG
from . import entity_graph_edit as GE
from . import talent_add_stat as TA
from . import talent_values as TV

#: A multiply of a value by a literal 1.0: Carmilla's POWER radius.
DONOR_MUL_HERO = "Carmilla"
DONOR_MUL_FILE = "Hero_Carmilla"
DONOR_MUL = "Primary Ability Radius Operation"
#: A value node that reads a selector, and the caster's node that reads it.
DONOR_FACTOR_HERO = "Melusine"
DONOR_FACTOR_FILE = "Hero_Melusine"
DONOR_FACTOR = "Skill Power Chill Extra Radius"
DONOR_GET_FILE = "Hero_Melusine_Power_Caster_Model"
DONOR_GET = "Owner Skill Power Chill Extra Radius"

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


def add_factor(raw: bytes, during_raw: bytes, factor_raw: bytes, *, talent: str, values,
               tag: str, percent: bool = True, seed: str = "") -> tuple[bytes, Factor]:
    """Return the file holding ``talent`` with a factor node (step 1)."""
    amounts = TA.normalise_values(values)
    graph = EG.parse(raw)
    state, first, fmt = TA.talent_parts(graph, talent)
    ctl = next(c for c in graph.components if c.name == f"Skill Controller {talent}")
    sel = TA._float_selector(raw, graph, f"Skill {talent}", ctl.guid, first)
    base = f"Skill {talent} Range {tag}"
    show, mult, cond, fac = f"{base} Selector", f"{base} Factor Selector", \
        f"{base} Condition Selector", f"{base} Factor"
    if any(c.name == fac for c in graph.components):
        raise RangeError(f"talent {talent!r} already scales {tag!r}")
    group = f"Skill {talent}"
    ef = GE.EntityFile(raw)
    during, donor = GE.EntityFile(during_raw), GE.EntityFile(factor_raw)
    seed = f"{seed or talent}:range:{tag}"
    try:
        ef.clone([sel.name], rename={sel.name: show}, seed=seed + ":show")
        ef.clone([sel.name], rename={sel.name: mult}, seed=seed + ":mult")
        dgrp = during.component(TA.DONOR_DURING_SELECTOR).group
        ef.clone([TA.DONOR_DURING_SELECTOR], rename={TA.DONOR_DURING_SELECTOR: cond},
                 group={dgrp: group}, source=during, seed=seed + ":cond")
        ef.set_ref(cond, "entries[0][0]", state.name)        # while the talent is owned
        ef.set_ref(cond, "entries[0][1]", mult)              # 1 + its amount
        ef.set_value(cond, "entries[1][1]", 1.0)             # else 1: no change
        fgrp = donor.component(DONOR_FACTOR).group
        ef.clone([DONOR_FACTOR], rename={DONOR_FACTOR: fac}, group={fgrp: group},
                 source=donor, seed=seed + ":factor")
        ef.set_ref(fac, "value", cond)
        slot = ef.add_format_slot(fmt.name, show, percent=percent) if fmt else None
        out = ef.to_bytes()
    except GE.EntityEditError as e:
        raise RangeError(f"talent {talent!r}: {e}") from e
    for name, shift in ((show, 0.0), (mult, 1.0)):
        tiers = TV.tier_values(out, name)
        written: dict[int, float] = {}
        for tier in TA.TIERS:
            index = tiers[tier][0]
            if index in written and written[index] != amounts[tier] + shift:
                raise RangeError(f"talent {talent!r}: its card shares one number between "
                                 f"rarities (including {tier}); give those rarities the same value")
            written[index] = amounts[tier] + shift
        for index, amount in written.items():
            out = TV.set_union_value(out, name, index, amount)
    return out, Factor(fac, show, slot)


def reader(raw: bytes, get_raw: bytes, *, factor_guid: bytes, factor_label: str,
           owner_resource: str, name: str, seed: str = "") -> bytes:
    """Return ``raw`` (another entity of the hero) with a node ``name`` reading
    the factor from the hero's entity (step 2). ``factor_label`` is the factor's
    reference label (``[Value] Hero_X\\Group\\Name``) and ``owner_resource`` the
    hero entity's resource path (``Heroes\\Hero_X\\Hero_X.entity.ot``)."""
    ef, donor = GE.EntityFile(raw), GE.EntityFile(get_raw)
    old = next(r.guid for r in donor.component(DONOR_GET).refs if r.path.endswith(DONOR_FACTOR))
    try:
        ef.clone([DONOR_GET], rename={DONOR_GET: name}, source=donor, seed=f"{seed}:get")
        if ef.retarget_external(name, old, factor_guid, factor_label) != 1:
            raise RangeError(f"{DONOR_GET!r} no longer reads {DONOR_FACTOR!r}")
        ef.set_value(name, "template[1]", owner_resource)
        return ef.to_bytes()
    except GE.EntityEditError as e:
        raise RangeError(str(e)) from e


def _activate_before(ef: GE.EntityFile, node: str, new: list[str]) -> int:
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
        lists += 1
    return lists


def scale_node(raw: bytes, mul_raw: bytes, *, node: str, factor: str, seed: str = "",
               activate: tuple[str, ...] = ()) -> bytes:
    """Return ``raw`` with ``node`` multiplied by ``factor``, a node of the same
    file (step 3). ``activate`` are nodes added for it (the reader of step 2):
    wherever a state switches ``node`` on, they are switched on first."""
    kind = how_scaled(raw, node)
    ef = GE.EntityFile(raw)
    try:
        if kind == "multiply":
            ef.append_operand(node, factor)
            _activate_before(ef, node, list(activate))
            return ef.to_bytes()
        c = ef.component(node)
        base, scaled = f"{node} Base", f"{node} Scaled"
        if any(x.name in (base, scaled) for x in ef.graph().components):
            raise RangeError(f"{node!r} is already scaled")
        ef.clone([node], rename={node: base}, seed=f"{seed}:{node}:base")
        donor = GE.EntityFile(mul_raw)
        ef.clone([DONOR_MUL], rename={DONOR_MUL: scaled},
                 group={donor.component(DONOR_MUL).group: c.group}, source=donor,
                 seed=f"{seed}:{node}:scaled")
        ef.set_ref(scaled, "operations[0]", base)
        ef.source_value(scaled, 1, factor)
        ef.source_value(node, 0, scaled)
        _activate_before(ef, node, [*activate, base, scaled])
        return ef.to_bytes()
    except GE.EntityEditError as e:
        raise RangeError(f"{node!r}: {e}") from e


def reads_owner(raw: bytes, owner_resource: str) -> bool:
    """Whether a shipped get-value node of this entity reads ``owner_resource``
    (the hero's entity). Only such entities may read the factor across files: a
    read that finds nothing gives 0, and a radius multiplied by 0 is an ability
    with no area. Every hero has some (Melusine's caster, Piper's projectile,
    Romeo's rose; surveyed 2026-10-09)."""
    return any(c.cls.endswith("GetValueSettings") and owner_resource in "".join(c.literals)
               for c in EG.parse(raw).components)


_SIZE = re.compile(r"radius|range|length|width|size|scale|distance|area", re.I)
_NOT_GAMEPLAY = re.compile(r"fx|camera|mesh|decal|gauge|anim|shader|sound|fmod|\bui\b|preview|"
                           r"smooth|shadow|marker|light|collision|detection|recall|follow", re.I)
#: The ability a node's group names, as the cards name the buttons.
_GROUP_ABILITY = (("Ability Basic", "ATTACK"), ("Ability Primary", "POWER"),
                  ("Ability Secondary", "SPECIAL"), ("Ability Defensive", "DEFENSE"),
                  ("Ability Trait", "TRAIT"), ("Ability Dash", "DASH"),
                  ("Ability Ultimate", "ULTIMATE"))


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
            out.append({"file": stem, "node": c.name, "ability": ability,
                        "where": None if stem == main else stem.removeprefix(main + "_"),
                        "value": None if how == "multiply" else float(value), "how": how})
    return out
