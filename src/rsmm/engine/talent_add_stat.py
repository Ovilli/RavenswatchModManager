"""Give a talent a stat bonus it does not have: "Fiery Dragon also -25% TRAIT cooldown".

The recipe was hand-written once (``wukong-twirl-finisher``) and PROVEN in game
2026-10-05; this is the general form, built on the ability editor's graph
primitives (``entity_graph_edit``). For a talent ``T`` of a hero:

1. **Selector.** Clone the talent's own rarity selector (``Skill T`` group, a
   Value Selector keyed on ``Skill Controller T``) and write the new numbers
   into its tiers. Keyed on T's controller, it reads the rarity of T's card.
2. **Modifier.** Clone Beowulf's ``Skill Trait Quest Complete CD Reduction
   Modifier`` - a self-targeted, permanent stat modifier, the one the proven
   recipe borrowed - point its ``amount`` at the new selector and set its stat.
3. **Owner.** Add the modifier to the ``while_active`` list of the ``Skill T``
   state, which T's controller switches on while the talent is owned (291 of
   292 talents with such a state, surveyed 2026-10-05). Adding, not replacing:
   121 of those states already run modifiers of their own, and the proven
   recipe's "swap the state" step only worked because Fiery Dragon's had none.
4. **Card.** Append a slot to the description format T's controller draws
   (usually ``Skill String Desc T``) reading the new selector,
   so the card text can show the number as ``{N}`` and it scales with rarity.

The amount is in the stat's own unit, as an item's modifier amount is: ``0.25``
on ``CD reduce trait`` is -25% TRAIT cooldown.

:func:`rebuild_talent` is the talent builder's first step: it turns a talent's
own effect OFF so the card can be rebuilt as a different talent. The
controller is pointed at a new, empty owned-state, so the original state never
switches on and nothing hanging off it runs; stats added afterwards attach to
the new state. The card's number slots are cleared, so the rebuilt card's
numbers start at ``{0}``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import entity_graph as EG
from . import entity_graph_edit as GE
from . import talent_values as TV
from .item_modifier import ItemModifierError, resolve_stat, set_modifier_stat

#: The proven donor: a self-targeted permanent stat modifier.
DONOR_HERO = "Beowulf"
DONOR_MODIFIER = "Skill Trait Quest Complete CD Reduction Modifier"

TIERS = TV.TIERS  # Common, Rare, Epic, Legendary

#: A conditional amount: ``[a State is active -> a number], [True -> 0]``. Shipped
#: in Aladdin's file (59 selectors in the game have this shape); copied and
#: re-pointed to make "while <ability> is active" (RE 2026-10-05).
DONOR_DURING_HERO = "Aladdin"
DONOR_DURING_SELECTOR = "Ability Trait Wish 1 Extra Damage Selector"

#: Button -> the hero's controller for it. The controller is what the button runs,
#: and its first State reference is the state active while the ability is used.
#: Its NAME is the button's; the state's name is the designers' and does not
#: always agree (Snow Queen's DEFENSE controller runs `State Ability Secondary`),
#: so the ability is always found through the controller, never by state name.
ABILITY_CONTROLLERS = {
    "ATTACK": "Basic Attack Controller",
    "POWER": "Primary Ability Controller",
    "SPECIAL": "Secondary Ability Controller",
    "DEFENSE": "Defensive Ability Controller",
    "TRAIT": "Trait Ability Controller",
}
ABILITIES = (*ABILITY_CONTROLLERS, "DASH")


def ability_state(graph: EG.EntityGraph, ability: str) -> EG.Component:
    """The state that is active while ``ability`` (ATTACK, POWER, SPECIAL,
    DEFENSE, TRAIT or DASH) is being used, or :class:`AddStatError` saying why
    this hero has none to read."""
    ability = ability.upper()
    if ability not in ABILITIES:
        raise AddStatError(f"unknown ability {ability!r}; use one of {', '.join(ABILITIES)}")
    states = [c for c in graph.components if c.cls.endswith("StateSettings")]
    if ability == "DASH":
        # The dash itself lives in the shared Hero_Common entity; a hero's file
        # carries its own child of that state.
        hit = next((c for c in states if c.name == "Child State Dash Ability"), None)
    else:
        by_guid = graph.by_guid()
        ctl = next((c for c in graph.components if c.group == "Hero Controller"
                    and c.name == ABILITY_CONTROLLERS[ability]), None)
        hit = None
        if ctl is not None:
            hit = next((by_guid[r.guid] for r in ctl.refs if r.guid in by_guid
                        and by_guid[r.guid].cls.endswith("StateSettings")), None)
        if hit is None and ability == "ATTACK":
            # The basic attack's controller picks between combos and names no
            # state; its umbrella state is the shortest "State ..." in its group.
            basic = sorted((c for c in states if c.group == "Ability Basic"
                            and c.name.startswith("State ")), key=lambda c: len(c.name))
            hit = basic[0] if basic else None
    if hit is None:
        raise AddStatError(f"this hero has no state that marks {ability} as in use, "
                           "so 'during' cannot be built for it")
    if hit.name.startswith("Event "):
        # A momentary event state flicks on at activation and off again: "during"
        # on it would almost never apply. Merlin's POWER/DEFENSE/TRAIT are like this.
        raise AddStatError(f"this hero's {ability} only signals its start ({hit.name!r}), "
                           "not that it is in use, so 'during' cannot be built for it")
    return hit


class AddStatError(ValueError):
    """The talent cannot take a stat bonus this way; the message says why."""


@dataclass(frozen=True)
class AddedStat:
    selector: str      # the new selector's component name
    modifier: str      # the new modifier's component name
    slot: int | None   # the card text's {N} for the new number, None without a card format


def talent_parts(graph: EG.EntityGraph, talent: str) -> tuple[EG.Component, EG.Component,
                                                                EG.Component | None]:
    """``(owned state, rarity selector, card description format)`` of a talent,
    or :class:`AddStatError` naming what is missing."""
    group = f"Skill {talent}"
    ctl = next((c for c in graph.components if c.name == f"Skill Controller {talent}"), None)
    if ctl is None:
        raise AddStatError(f"no talent {talent!r} here (no 'Skill Controller {talent}')")
    state = owned_state(graph, ctl, talent)
    selectors = [c for c in graph.components
                 if c.group == group and c.cls.endswith("ValueSelectorSettings")
                 and any(r.guid == ctl.guid for r in c.refs)]
    if not selectors:
        raise AddStatError(f"talent {talent!r} has no per-rarity number to copy, "
                           "so a new number could not scale with rarity")
    # The card's text format is the one the controller references, not the one
    # its name suggests: some cards draw text keyed differently from their row
    # (Wukong's `Dash Attack` draws `Skill_Attack_After_Dash`).
    by_guid = graph.by_guid()
    fmts = [by_guid[r.guid] for r in ctl.refs if r.guid in by_guid
            and by_guid[r.guid].cls.endswith("StringFormatValueSettings")]
    fmt = next((c for c in fmts if "Desc" in c.name), fmts[-1] if fmts else None)
    return state, selectors[0], fmt


def owned_state(graph: EG.EntityGraph, ctl: EG.Component, talent: str) -> EG.Component:
    """The state the controller switches on while the talent is owned.

    Found through the controller's own reference rather than by name, so after
    :func:`rebuild_talent` it is the new, empty state. The talent's original
    ``Skill <T>`` state is preferred when the controller still points at it."""
    by_guid = graph.by_guid()
    states = [by_guid[r.guid] for r in ctl.refs if r.guid in by_guid
              and by_guid[r.guid].cls.endswith("StateSettings")]
    if not states:
        raise AddStatError(f"talent {talent!r} has no state that marks it as owned, "
                           "so there is nothing to attach a stat to (ultimates are like this)")
    named = [s for s in states if s.name in (f"Skill {talent}", rebuilt_name(talent))]
    return (named or states)[0]


def rebuilt_name(talent: str) -> str:
    return f"Skill {talent} Rebuilt"


def rebuild_talent(raw: bytes, *, talent: str, seed: str = "") -> tuple[bytes, int]:
    """Turn ``talent``'s own effect off, keeping its card; returns the file and
    how many number slots its card had (all cleared).

    The controller's owned-state reference moves to a copy of that state with
    every list emptied, so the original never switches on: whatever the talent
    did hangs off that state, or tests it. What the talent then does is only
    what is added to it (``add_stat``)."""
    graph = EG.parse(raw)
    ctl = next((c for c in graph.components if c.name == f"Skill Controller {talent}"), None)
    if ctl is None:
        raise AddStatError(f"no talent {talent!r} here (no 'Skill Controller {talent}')")
    if any(c.name == rebuilt_name(talent) for c in graph.components):
        raise AddStatError(f"talent {talent!r} is already rebuilt")
    state = owned_state(graph, ctl, talent)
    _s, _sel, fmt = talent_parts(graph, talent)

    from . import entity_fields as EF
    ef = GE.EntityFile(raw)
    try:
        new = rebuilt_name(talent)
        ef.clone([state.name], rename={state.name: new}, seed=(seed or talent) + ":rebuild")
        for f in EF.fields(ef.component(new)):
            if f.kind == "ref[]":
                for _ in range(len(f.items)):
                    ef.remove_ref(new, f.name, 0)
        moved = 0
        for f in EF.fields(ef.component(ctl.name)):
            if f.kind == "ref" and ctl.body[f.offset + 8:f.offset + 24] == state.guid:
                ef.set_ref(ctl.name, f.name, new)
                moved += 1
        if not moved:
            raise AddStatError(f"talent {talent!r}: its controller does not hold its state "
                               "in a plain reference; refusing to guess")
        cleared = ef.clear_format_slots(fmt.name) if fmt is not None else 0
        return ef.to_bytes(), cleared
    except GE.EntityEditError as e:
        raise AddStatError(f"talent {talent!r}: {e}") from e


def _float_selector(raw: bytes, graph: EG.EntityGraph, group: str, ctl_guid: bytes,
                    first: EG.Component) -> EG.Component:
    """Prefer a selector whose tiers are floats: an int one would truncate 0.25 to 0."""
    for c in [first, *(c for c in graph.components if c.group == group and c is not first
                       and c.cls.endswith("ValueSelectorSettings")
                       and any(r.guid == ctl_guid for r in c.refs))]:
        tiers = TV.tier_values(raw, c.name)
        if tiers and all(t[2] == TV.TYPE_F32 for t in tiers.values()):
            return c
    raise AddStatError(f"{group!r} has no decimal per-rarity number to copy")


def normalise_values(values) -> dict[str, float]:
    """``{tier: amount}`` from one number, a 4-list (Common..Legendary), or a table."""
    if isinstance(values, int | float) and not isinstance(values, bool):
        return {t: float(values) for t in TIERS}
    if isinstance(values, list | tuple):
        if len(values) != 4 or not all(isinstance(v, int | float) for v in values):
            raise AddStatError(f"values must be 4 numbers (Common, Rare, Epic, Legendary), "
                               f"got {values!r}")
        return dict(zip(TIERS, (float(v) for v in values), strict=True))
    if isinstance(values, dict):
        out = {}
        for k, v in values.items():
            tier = next((t for t in TIERS if t.lower() == str(k).lower()), None)
            if tier is None or not isinstance(v, int | float):
                raise AddStatError(f"values: {k!r} = {v!r} is not a rarity and a number")
            out[tier] = float(v)
        missing = [t for t in TIERS if t not in out]
        if missing:
            raise AddStatError(f"values: missing {', '.join(missing)}")
        return out
    raise AddStatError(f"values must be a number, a list of 4 or a table, got {values!r}")


def add_stat(raw: bytes, donor_raw: bytes, *, talent: str, stat: str | int,
             values, percent: bool = True, seed: str = "", during: str | None = None,
             during_donor_raw: bytes | None = None) -> tuple[bytes, AddedStat]:
    """Return ``raw`` (the hero entity holding ``talent``) with the stat bonus added.

    ``during`` (an ability, e.g. ``"DEFENSE"``) makes the bonus apply only while
    that ability is in use: the modifier's amount reads a copy of
    :data:`DONOR_DURING_SELECTOR` ("ability state active -> the per-rarity
    number, else 0"), taken from ``during_donor_raw`` (the Aladdin entity)."""
    try:
        key = resolve_stat(stat)
    except ItemModifierError as e:
        raise AddStatError(str(e)) from e
    amounts = normalise_values(values)

    graph = EG.parse(raw)
    state, first_sel, fmt = talent_parts(graph, talent)
    ctl = next(c for c in graph.components if c.name == f"Skill Controller {talent}")
    sel = _float_selector(raw, graph, f"Skill {talent}", ctl.guid, first_sel)

    tag = f"{key:08x}"
    cond_state = None
    if during:
        cond_state = ability_state(graph, during)
        tag += f" During {during.upper()}"
        if during_donor_raw is None:
            raise AddStatError(f"'during' needs the game's {DONOR_DURING_HERO} files")
    new_sel = f"Skill {talent} Added {tag} Selector"
    new_mod = f"Skill {talent} Added {tag} Modifier"
    new_cond = f"Skill {talent} Added {tag} Condition Selector"
    if any(c.name in (new_sel, new_mod) for c in graph.components):
        raise AddStatError(f"talent {talent!r} already gets this stat from an earlier entry")

    ef = GE.EntityFile(raw)
    donor = GE.EntityFile(donor_raw)
    seed = seed or f"{talent}:{tag}"
    try:
        ef.clone([sel.name], rename={sel.name: new_sel}, seed=seed + ":sel")
        donor_mod = donor.component(DONOR_MODIFIER)
        ef.clone([DONOR_MODIFIER], rename={DONOR_MODIFIER: new_mod},
                 group={donor_mod.group: f"Skill {talent}"}, source=donor, seed=seed + ":mod")
        amount = new_sel
        if cond_state is not None:
            src = GE.EntityFile(during_donor_raw)
            grp = src.component(DONOR_DURING_SELECTOR).group
            ef.clone([DONOR_DURING_SELECTOR], rename={DONOR_DURING_SELECTOR: new_cond},
                     group={grp: f"Skill {talent}"}, source=src, seed=seed + ":cond")
            ef.set_ref(new_cond, "entries[0][0]", cond_state.name)   # while this is active
            ef.set_ref(new_cond, "entries[0][1]", new_sel)           # the per-rarity number
            amount = new_cond                                        # else 0
        ef.set_ref(new_mod, "amount", amount)
        ef.add_ref(state.name, "while_active", new_mod)
        slot = ef.add_format_slot(fmt.name, new_sel, percent=percent) if fmt else None
        out = ef.to_bytes()
    except GE.EntityEditError as e:
        raise AddStatError(f"talent {talent!r}: {e}") from e

    try:
        out = set_modifier_stat(out, new_mod, key)
    except ItemModifierError as e:
        raise AddStatError(f"talent {talent!r}: {e}") from e
    tiers = TV.tier_values(out, new_sel)
    written: dict[int, float] = {}
    for tier in TIERS:
        index = tiers[tier][0]
        if index in written and written[index] != amounts[tier]:
            raise AddStatError(
                f"talent {talent!r}: its card shares one number between rarities "
                f"(including {tier}); give those rarities the same value")
        written[index] = amounts[tier]
    for index, amount in written.items():
        out = TV.set_union_value(out, new_sel, index, amount)
    return out, AddedStat(new_sel, new_mod, slot)


def stat_key_bytes(stat: str | int) -> bytes:
    """The 4 bytes a modifier stores for ``stat`` (tests and diagnostics)."""
    return struct.pack("<I", resolve_stat(stat))
