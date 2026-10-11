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

from . import entity_fields as EF
from . import entity_graph as EG
from . import entity_graph_edit as GE
from . import talent_values as TV
from .item_modifier import ItemModifierError, modifier_survey, resolve_stat, set_modifier_stat

#: The proven donor: a self-targeted permanent stat modifier.
DONOR_HERO = "Beowulf"
DONOR_MODIFIER = "Skill Trait Quest Complete CD Reduction Modifier"

TIERS = TV.TIERS  # Common, Rare, Epic, Legendary

#: A conditional amount: ``[a State is active -> a number], [True -> 0]``. Shipped
#: in Aladdin's file (59 selectors in the game have this shape); copied and
#: re-pointed to make "while <ability> is active" (RE 2026-10-05).
DONOR_DURING_HERO = "Aladdin"
DONOR_DURING_SELECTOR = "Ability Trait Wish 1 Extra Damage Selector"

#: "For N s after X": an event state that switches a window state off and on
#: (copied from Beowulf's Retaliation, ``Skill Attack Flurry``, whose event
#: restarts a timer from DEFENSE) and a copy of its timer, run by the window, whose
#: ``state`` ENDS the window after N s. That is the shape of Beowulf's Damage Aura
#: and Dragon Empowered UI: the event switches the state, the timer only ends it.
#: Both come from :data:`DONOR_HERO`'s file, already read for the modifier. The
#: bonus is then "during" the window.
DONOR_TIMER = "Skill Attack Flurry Timer"
DONOR_RESTART = "Event Skill Attack Flurry Reset Timer"

#: "At most once every M s" (``cooldown``): Romeo's Love Shield gate. Its kiss
#: event fires a tester that passes only while the shield's Active state is OFF
#: and its Available state is ON, and switches Active on; Active runs a timer
#: whose ``state`` ends it. Copied, Active lasts the cooldown and fires the
#: window's restart event, so a use during the cooldown finds Active on and
#: does nothing. Available is held on by the talent's owned state (a state in
#: ``while_active`` is shipped data, as ``include`` uses). Romeo's own cooldown
#: timer and Available tester are not copied: Active's own length is the gate.
DONOR_LIMITER_HERO = "Juliet"
DONOR_LIMITER_FILE = "Hero_Romeo_Juliet_Common"
DONOR_LIMITER_TESTER = "Skill Special Invulnerable Active Tester"
DONOR_LIMITER_ACTIVE = "State Skill Special Invulnerable Active"
DONOR_LIMITER_TIMER = "Skill Special Invulnerable Duration Timer"
DONOR_LIMITER_AVAILABLE = "State Skill Special Invulnerable Available"

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


def ability_state(graph: EG.EntityGraph, ability: str, *,
                  momentary_ok: bool = False) -> EG.Component:
    """The state that is active while ``ability`` (ATTACK, POWER, SPECIAL,
    DEFENSE, TRAIT or DASH) is being used, or :class:`AddStatError` saying why
    this hero has none to read. ``momentary_ok`` accepts a state that only
    flicks on as the ability starts: useless for "during", exactly right for
    "after" (which only needs the start)."""
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
    if hit.name.startswith("Event ") and not momentary_ok:
        # A momentary event state flicks on at activation and off again: "during"
        # on it would almost never apply. Merlin's POWER/DEFENSE/TRAIT are like this.
        raise AddStatError(f"this hero's {ability} only signals its start ({hit.name!r}), "
                           "not that it is in use, so 'during' cannot be built for it")
    return hit


class AddStatError(ValueError):
    """The talent cannot take a stat bonus this way; the message says why."""


def applied_on_hit() -> frozenset[int]:
    """Stat keys the game applies to whoever is HIT, never to its owner.

    A modifier names its targets as collector sub-objects; an EMPTY list means
    something else carries it onto its victims (an attack, a zone). Ignite,
    Bleed, Chilled, Vulnerable, Weak, Marked, Rooted ... are applied that way
    and almost never through a self collector (surveyed 2026-10-06: Vulnerable
    11 on hit vs 1 self; the rest 0 self). ``add_stat`` builds a SELF modifier,
    so one of these would debuff the player's own hero. Read from the game's
    files (:func:`item_modifier.modifier_survey`), so it follows a patch; empty
    when no game data is reachable."""
    survey = modifier_survey()
    return frozenset(k for k, v in survey.on_hit.items() if v > survey.on_self.get(k, 0))


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

    ef = GE.EntityFile(raw)
    try:
        new = rebuilt_name(talent)
        ef.clone([state.name], rename={state.name: new}, seed=(seed or talent) + ":rebuild")
        _empty_state(ef, new)
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


def include_talent(raw: bytes, *, talent: str, other: str) -> bytes:
    """Make owning ``talent`` also switch on ``other``'s effect (same hero).

    A talent's effect hangs off its owned state: modifiers in its lists, and
    gameplay nodes that TEST it. Red's Short Wick is the case that asked for
    this: its "bomb explodes on landing" is `Skill Secondary Ignite Quick Bombs
    Value`, a bool wired to "Short Wick's state is on", which the bomb reads
    (Pam, 2026-10-06: keep it available to Shapeshifter players). So ``other``'s
    owned state is added to ``talent``'s ``while_active``: while ``talent`` is
    owned, ``other``'s state is on and everything it does or gates runs. States
    holding states in ``while_active`` is shipped data (Wukong's DEFENSE,
    Beowulf's Damage Aura). Numbers keyed on ``other``'s rarity read its own
    card's tier, which an unowned card does not have: they take the selector's
    last (fallback) entry, the Common value in every shipped talent selector."""
    if talent == other:
        raise AddStatError(f"talent {talent!r} cannot include itself")
    graph = EG.parse(raw)
    ctls = {n: next((c for c in graph.components if c.name == f"Skill Controller {n}"), None)
            for n in (talent, other)}
    for n, c in ctls.items():
        if c is None:
            raise AddStatError(f"no talent {n!r} here (no 'Skill Controller {n}')")
    mine = owned_state(graph, ctls[talent], talent)
    theirs = owned_state(graph, ctls[other], other)
    already = [r for r in mine.refs if r.guid == theirs.guid]
    if already:
        raise AddStatError(f"talent {talent!r} already includes {other!r}")
    ef = GE.EntityFile(raw)
    try:
        ef.add_ref(mine.name, "while_active", theirs.name)
        return ef.to_bytes()
    except GE.EntityEditError as e:
        raise AddStatError(f"talent {talent!r}: {e}") from e


#: Entities every hero inherits (checked 2026-10-09 on all 11 playable heroes): a
#: copied effect may keep its links into these, whichever hero it moves to.
SHARED_SCOPES = frozenset({"Character_Common", "Hero_Common", "Hero_Common_Update5"})


#: Node kinds that only hold or work out a number. An effect made of nothing
#: else does nothing on another hero: something of its own hero reads it, by a
#: path no reference shows (Melusine's Crescendo, Carmilla's Blood Reserve).
_PASSIVE = ("StateSettings", "ValueSettings", "ValueSelectorSettings",
            "ValueOperationsSettings", "ValueOperationSettings", "SelectorSettings")


def borrowable(raw: bytes | EG.EntityGraph, other: str, *,
               readers: list[bytes | EG.EntityGraph] = ()) -> list[str]:
    """The components that make up talent ``other``'s effect, when the effect can
    run on another hero; otherwise :class:`AddStatError` saying why.

    ``raw`` is the file holding ``other``'s owned state; ``readers`` are its
    hero's other entity files (each bytes, or already parsed, to list many).
    The effect is what hangs off the owned state (modifiers, testers, timers, fx
    ...). It moves only when it is whole: nothing else reads it, the talent's own
    controller excepted (its card and the selectors keyed on its rarity), it links
    nowhere but into itself and :data:`SHARED_SCOPES`, it loads no resource, and
    something in it acts (see :data:`_PASSIVE`). Most talents fail this: their
    number is read by their hero's ability graph (Aladdin's Defense Tornado's damage
    multiplier is read by his DEFENSE tornado), which is not there on another hero.
    9 of 343 shipped talents pass (survey 2026-10-09): Wukong's Focused Strikes,
    Piper's Virtuoso, Melusine's Soothing Presence and Dance Step, Aladdin's Master
    Thief and Jinniya's Gift, Carmilla's Bat Master, Juliet's Wedding Gifts,
    Merlin's Astrology."""
    graph = raw if isinstance(raw, EG.EntityGraph) else EG.parse(raw)
    ctl = next((c for c in graph.components if c.name == f"Skill Controller {other}"), None)
    if ctl is None:
        raise AddStatError(f"no talent {other!r} here (no 'Skill Controller {other}')")
    state = owned_state(graph, ctl, other)
    by_guid = graph.by_guid()
    if state.guid not in by_guid:
        raise AddStatError(f"talent {other!r} is built in another file")
    seen = {state.guid}
    todo = [state]
    while todo:
        for r in todo.pop().refs:
            if r.guid == ctl.guid or r.guid == bytes(16):
                continue
            t = by_guid.get(r.guid)
            if t is None:
                if r.scope and r.scope not in SHARED_SCOPES:
                    raise AddStatError(f"talent {other!r} uses {r.path}, which another hero "
                                       "does not have")
                continue
            if t.name.startswith("Skill Controller "):
                raise AddStatError(f"talent {other!r} depends on another talent "
                                   f"({t.name[len('Skill Controller '):]!r})")
            if t.guid not in seen:
                seen.add(t.guid)
                todo.append(t)
    if len(seen) == 1:
        raise AddStatError(f"talent {other!r} does its work inside its hero's abilities, "
                           "not through its own state, so it cannot move to another hero")
    for x in seen:
        loads = _weak_resources(by_guid[x])
        if loads:
            # Not in this hero's preload caches: it would load as null and can
            # crash the game (engine/CLAUDE.md). Geppetto's Flash of Genius.
            raise AddStatError(f"talent {other!r} loads {loads[0]}, which another hero "
                               "does not load; borrowing it is not supported")
    if all(by_guid[x].cls.endswith(_PASSIVE) for x in seen):
        raise AddStatError(f"talent {other!r} holds only numbers that its hero reads "
                           "elsewhere, so on another hero it would do nothing")
    mine = seen | {ctl.guid}
    for g in [graph, *(b if isinstance(b, EG.EntityGraph) else EG.parse(b) for b in readers)]:
        for c in g.components:
            if c.guid in seen or c.guid == ctl.guid or c.name.startswith("Skill Controller ") \
                    or c.cls.endswith("StringFormatValueSettings"):
                continue
            hit = next((r for r in c.refs if r.guid in mine), None)
            if hit is not None:
                raise AddStatError(
                    f"talent {other!r} works through its hero's own abilities ({c.name!r} in "
                    f"{g.name or 'its file'} reads {hit.path.rsplit(chr(92), 1)[-1]!r}), so it "
                    "cannot move to another hero")
    return [c.name for c in graph.components if c.guid in seen]


def _weak_resources(c: EG.Component) -> list[str]:
    """Resource paths ``c`` names through a weak reference (archive, path)."""
    if "oCResourceWeakRef" not in c.classes:
        return []
    from . import cooked
    from . import entity_strings as ES
    tag = cooked.MARK_BEGIN + struct.pack("<I", c.classes.index("oCResourceWeakRef"))
    out = []
    i = c.body.find(tag)
    while i >= 0:
        strs = [t for _o, t in ES._scan_payload(c.body[i + 8:c.body.find(cooked.MARK_END, i)])]
        if len(strs) >= 2 and strs[1]:
            out.append(strs[1])
        i = c.body.find(tag, i + 1)
    return out


def borrow_talent(raw: bytes, donor_raw: bytes, *, talent: str, other: str, hero: str,
                  readers: list[bytes | EG.EntityGraph] = (), seed: str = "") -> bytes:
    """Make owning ``talent`` also run ``other``'s effect, ``other`` being a
    talent of another hero (``hero``, whose file is ``donor_raw``).

    :func:`include_talent` across heroes: ``other``'s effect (see
    :func:`borrowable`) is copied into this file, renamed ``... From <hero>``, and
    its copied owned state is added to ``talent``'s ``while_active``. Numbers
    keyed on ``other``'s rarity are re-keyed on ``talent``'s controller, so they
    follow THIS card's rarity (a same-hero include reads the Common value)."""
    names = borrowable(donor_raw, other, readers=readers)
    graph = EG.parse(raw)
    ctl = next((c for c in graph.components if c.name == f"Skill Controller {talent}"), None)
    if ctl is None:
        raise AddStatError(f"no talent {talent!r} here (no 'Skill Controller {talent}')")
    mine = owned_state(graph, ctl, talent)
    donor = GE.EntityFile(donor_raw)
    dg = donor.graph()
    dctl = next(c for c in dg.components if c.name == f"Skill Controller {other}")
    dstate = owned_state(dg, dctl, other)
    tag = f" From {hero}"
    rename = {n: n + tag for n in names}
    groups = {c.group for c in dg.components if c.name in rename}
    if any(c.name in rename.values() for c in graph.components):
        raise AddStatError(f"talent {talent!r} already includes {hero}'s {other!r}")
    ef = GE.EntityFile(raw)
    try:
        ef.clone(names, rename=rename, group={g: g + tag for g in groups}, source=donor,
                 seed=f"{seed or talent}:borrow:{hero}:{other}")
        for new in rename.values():
            ef.swap_refs(new, dctl.guid, ctl.name)
            if dctl.guid in ef.component(new).body:
                raise AddStatError(f"{new!r} still names {other!r}'s controller where "
                                   "this edit cannot reach it")
        ef.add_ref(mine.name, "while_active", rename[dstate.name])
        out = ef.to_bytes()
    except GE.EntityEditError as e:
        raise AddStatError(f"talent {talent!r}: {e}") from e
    # Backstop for borrowable's own check: a resource this hero's preload
    # caches do not list loads as null and can crash the game.
    from .entity_check import resource_paths
    new = sorted(resource_paths(out) - resource_paths(raw))
    if new:
        raise AddStatError(f"{hero}'s {other!r} loads {', '.join(new)}, which this hero "
                           "does not load; borrowing it is not supported")
    return out


def _empty_state(ef: GE.EntityFile, name: str) -> None:
    """Remove every reference from every list of state ``name``."""
    for f in EF.fields(ef.component(name)):
        if f.kind == "ref[]":
            for _ in range(len(f.items)):
                ef.remove_ref(name, f.name, 0)


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
             during_donor_raw: bytes | None = None, after: str | None = None,
             seconds: float | None = None, cooldown: float | None = None,
             limiter_donor_raw: bytes | None = None,
             next_ability: str | None = None) -> tuple[bytes, AddedStat]:
    """Return ``raw`` (the hero entity holding ``talent``) with the stat bonus added.

    ``during`` (an ability, e.g. ``"DEFENSE"``) makes the bonus apply only while
    that ability is in use: the modifier's amount reads a copy of
    :data:`DONOR_DURING_SELECTOR` ("ability state active -> the per-rarity
    number, else 0"), taken from ``during_donor_raw`` (the Aladdin entity).

    ``after`` (an ability) with ``seconds`` makes it apply for that long each
    time the ability is used, restarting on every use: the ability switches a
    window state on (off and on again if it already was) and the window's timer
    (:data:`DONOR_TIMER`) ends it; read through the same selector as ``during``.

    ``cooldown`` (with ``after``) lets the ability restart the window at most
    once every that many seconds, counted from the restart: a copy of Romeo's
    Love Shield gate (:data:`DONOR_LIMITER_TESTER`), taken from
    ``limiter_donor_raw`` (the ``Hero_Romeo_Juliet_Common`` entity).

    ``next_ability`` (with ``after``) makes the bonus last only until ability ``next``
    is next used: "within N s after DEFENSE, your next ATTACK ...". When that
    ability's state ENDS, a second copy of the restart event switches the window
    off, so the bonus covers that whole use and is gone after it. The list a
    state fires on exit is ``disables_while_active?`` (named before this was
    known): DEFENSE's "Just Exit Timer", the dash's "Exit Event Sender" and
    Romeo's Love Shield cooldown, which starts as the shield ends, all sit
    there (survey 2026-10-08)."""
    try:
        key = resolve_stat(stat)
    except ItemModifierError as e:
        raise AddStatError(str(e)) from e
    from .item_modifier import game_state_keys
    if key in game_state_keys():
        raise AddStatError(f"{stat!r} is game state (scene, menu, day/night), not a stat "
                           "a modifier can change")
    if key in applied_on_hit():
        raise AddStatError(
            f"{stat!r} is something the game puts on whoever is hit, and an added stat "
            f"applies to the hero itself, so {talent!r} would debuff its own hero")
    amounts = normalise_values(values)

    graph = EG.parse(raw)
    state, first_sel, fmt = talent_parts(graph, talent)
    ctl = next(c for c in graph.components if c.name == f"Skill Controller {talent}")
    sel = _float_selector(raw, graph, f"Skill {talent}", ctl.guid, first_sel)

    tag = f"{key:08x}"
    cond_state = None
    hook = None
    if during and after:
        raise AddStatError("give 'during' or 'after', not both")
    if during:
        cond_state = ability_state(graph, during)
        tag += f" During {during.upper()}"
    if after:
        if not isinstance(seconds, int | float) or isinstance(seconds, bool) or seconds <= 0:
            raise AddStatError(f"'after' needs how many seconds it lasts, got {seconds!r}")
        hook = ability_state(graph, after, momentary_ok=True)
        tag += f" After {after.upper()}"
    used_up = None
    if next_ability is not None:
        if not after:
            raise AddStatError("'next' ends an 'after' window when that ability is used; "
                               "give 'after' too")
        if next_ability.upper() == after.upper():
            raise AddStatError(f"'next' is {next_ability.upper()}, the ability that starts the "
                               "window; the bonus would only ever cover that same use")
        # The window must last the whole use, so a state that only flicks on as
        # the ability starts (Merlin) would end it before anything lands.
        used_up = ability_state(graph, next_ability)
        tag += f" Next {next_ability.upper()}"
    if cooldown is not None:
        if not after:
            raise AddStatError("'cooldown' limits how often 'after' restarts; give 'after' too")
        if not isinstance(cooldown, int | float) or isinstance(cooldown, bool) or cooldown <= 0:
            raise AddStatError(f"'cooldown' needs a number of seconds above 0, got {cooldown!r}")
        if limiter_donor_raw is None:
            raise AddStatError(f"'cooldown' needs the game's {DONOR_LIMITER_FILE} file")
    if (during or after) and during_donor_raw is None:
        raise AddStatError(f"'{'during' if during else 'after'}' needs the game's "
                           f"{DONOR_DURING_HERO} files")
    new_sel = f"Skill {talent} Added {tag} Selector"
    new_mod = f"Skill {talent} Added {tag} Modifier"
    new_cond = f"Skill {talent} Added {tag} Condition Selector"
    new_win = f"Skill {talent} Added {tag} Window"
    new_timer = f"Skill {talent} Added {tag} Window Timer"
    new_restart = f"Event Skill {talent} Added {tag} Window Restart"
    new_consume = f"Event Skill {talent} Added {tag} Window Used Up"
    new_gate = f"Skill {talent} Added {tag} Cooldown Tester"
    new_gate_on = f"Skill {talent} Added {tag} Cooldown"
    new_gate_timer = f"Skill {talent} Added {tag} Cooldown Timer"
    new_gate_ready = f"Skill {talent} Added {tag} Cooldown Available"
    if any(c.name in (new_sel, new_mod) for c in graph.components):
        raise AddStatError(f"talent {talent!r} already gets this stat from an earlier entry")

    ef = GE.EntityFile(raw)
    donor = GE.EntityFile(donor_raw)
    # The tag is always part of it: the talent kind passes one seed per block,
    # and two stats on one talent copy the same selector, so without the tag
    # their copies minted the same GUID and the second entry failed.
    seed = f"{seed or talent}:{tag}"
    try:
        ef.clone([sel.name], rename={sel.name: new_sel}, seed=seed + ":sel")
        donor_mod = donor.component(DONOR_MODIFIER)
        ef.clone([DONOR_MODIFIER], rename={DONOR_MODIFIER: new_mod},
                 group={donor_mod.group: f"Skill {talent}"}, source=donor, seed=seed + ":mod")
        amount = new_sel
        if hook is not None:
            # The window: an empty copy of the talent's own state. Using the
            # ability fires a copy of Retaliation's restart event, re-pointed to
            # switch the WINDOW off and on; the window runs a copy of the timer,
            # whose `state` ENDS the window when `seconds` run out. A timer's
            # `state` never switches a state on (playtest 2026-10-06: pointing
            # only the timer at the window, the window never came on); this is
            # Beowulf's Damage Aura shape (proc event -> state, state -> timer).
            ef.clone([state.name], rename={state.name: new_win}, seed=seed + ":win")
            _empty_state(ef, new_win)
            dgrp = donor.component(DONOR_TIMER).group
            ef.clone([DONOR_TIMER, DONOR_RESTART],
                     rename={DONOR_TIMER: new_timer, DONOR_RESTART: new_restart},
                     group={dgrp: f"Skill {talent}"}, source=donor, seed=seed + ":timer")
            ef.set_ref(new_restart, "activates[0]", new_win)
            ef.set_ref(new_restart, "deactivates?[0]", new_win)
            ef.add_ref(new_win, "while_active", new_timer)
            ef.set_ref(new_timer, "state", new_win)
            ef.set_value(new_timer, "duration", float(seconds))
            if used_up is not None:
                # A copy of the restart event that only switches the window
                # off, fired as `next`'s ability ends.
                ef.clone([DONOR_RESTART], rename={DONOR_RESTART: new_consume},
                         group={dgrp: f"Skill {talent}"}, source=donor, seed=seed + ":next")
                ef.remove_ref(new_consume, "activates", 0)
                ef.set_ref(new_consume, "deactivates?[0]", new_win)
                ef.add_ref(used_up.name, "disables_while_active?", new_consume)
            if cooldown is None:
                ef.add_ref(hook.name, "activates", new_restart)
            else:
                _add_limiter(ef, GE.EntityFile(limiter_donor_raw), state=state.name,
                             hook=hook.name, restart=new_restart, seconds=float(cooldown),
                             names=(new_gate, new_gate_on, new_gate_timer, new_gate_ready),
                             group=f"Skill {talent}", seed=seed + ":gate")
            cond_state = ef.component(new_win)
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


def _add_limiter(ef: GE.EntityFile, donor: GE.EntityFile, *, state: str, hook: str,
                 restart: str, seconds: float, names: tuple[str, str, str, str],
                 group: str, seed: str) -> None:
    """Fire ``restart`` from ``hook`` at most once every ``seconds``.

    Copies Romeo's Love Shield gate (tester, Active, its timer, Available) as
    one set, so the tester's two sub-tests and Active's timer point at the
    copies. Every list on the copied states is emptied first: Romeo's Active
    also runs his invincibility and shield FX, and his cooldown timer, none of
    which may come along."""
    tester, on, timer, ready = names
    dgrp = donor.component(DONOR_LIMITER_TESTER).group
    ef.clone([DONOR_LIMITER_TESTER, DONOR_LIMITER_ACTIVE, DONOR_LIMITER_TIMER,
              DONOR_LIMITER_AVAILABLE],
             rename={DONOR_LIMITER_TESTER: tester, DONOR_LIMITER_ACTIVE: on,
                     DONOR_LIMITER_TIMER: timer, DONOR_LIMITER_AVAILABLE: ready},
             group={dgrp: group}, source=donor, seed=seed)
    _empty_state(ef, on)
    _empty_state(ef, ready)
    ef.add_ref(on, "activates", timer)        # Active starts its timer (Romeo's own wiring)
    ef.add_ref(on, "activates", restart)      # ...and restarts the bonus window
    ef.set_ref(timer, "state", on)            # the timer ENDS Active: the gate reopens
    ef.set_value(timer, "duration", seconds)  # Romeo reads his from a value; make it literal
    ef.add_ref(state, "while_active", ready)  # Available is on while the talent is owned
    ef.add_ref(hook, "activates", tester)


def stat_key_bytes(stat: str | int) -> bytes:
    """The 4 bytes a modifier stores for ``stat`` (tests and diagnostics)."""
    return struct.pack("<I", resolve_stat(stat))
