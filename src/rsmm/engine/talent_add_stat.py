"""Give a talent a stat bonus it does not have: "Fiery Dragon also -25% TRAIT cooldown".

The recipe was hand-written once (``wukong-twirl-finisher``) and PROVEN in game
2026-10-05; this is the general form, built on the ability editor's graph
primitives (``entity_graph_edit``). For a talent ``T`` of a hero:

1. **Selector.** A new per-rarity selector (``Skill T`` group) keyed on ``Skill
   Controller T``, holding the new numbers: it reads the rarity of T's card.
2. **Modifier.** A self-targeted, permanent stat modifier - the shape of
   Beowulf's ``Skill Trait Quest Complete CD Reduction Modifier``, which the
   proven recipe borrowed - whose ``amount`` reads the new selector.
3. **Owner.** Add the modifier to the ``while_active`` list of the ``Skill T``
   state, which T's controller switches on while the talent is owned (291 of
   292 talents with such a state, surveyed 2026-10-05). Adding, not replacing:
   121 of those states already run modifiers of their own, and the proven
   recipe's "swap the state" step only worked because Fiery Dragon's had none.
4. **Card.** Append a slot to the description format T's controller draws
   (usually ``Skill String Desc T``) reading the new selector,
   so the card text can show the number as ``{N}`` and it scales with rarity.

Every part is WRITTEN (``talent_writer``), not copied from another hero, which
is what these steps did until 2026-10-23 (Beowulf's modifier, timer and restart
event, Aladdin's "during" selector, Romeo's Love Shield gate): a talent mod
reads no file but the one it edits.

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

import functools
import struct
from dataclasses import dataclass

from . import entity_fields as EF
from . import entity_graph as EG
from . import entity_graph_edit as GE
from . import entity_parts as P
from . import talent_values as TV
from . import talent_writer as TW
from .item_modifier import (
    ItemModifierError,
    modifier_survey,
    resolve_stat,
    stat_catalog,
    stat_name,
)

TIERS = TV.TIERS  # Common, Rare, Epic, Legendary

#: Game events a talent's bonus can start from (``on``): the item triggers
#: (``item_effect.TRIGGERS``) an ability's own state does not already give
#: through ``after``. Shipped talents listen for damage_taken (Romeo's Panache)
#: and day_start / night_start (Wukong's Passive Reveal); the rest are proven
#: only on items so far.
TRIGGERS = ("damage_taken", "ultimate", "day_start", "night_start", "talent_picked",
            "item_picked_up", "dream_shards_gained", "sandman_purchase", "reroll")

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


def is_charge(stat: str | int) -> bool:
    """``Ability_Charge_<Ability>``: a count of extra charges, not a fraction."""
    try:
        name = stat_name(resolve_stat(stat))
    except ItemModifierError:
        return False
    return bool(name and name.startswith("Ability_Charge_"))


@functools.cache
def charges_heard() -> frozenset[int]:
    """Charge keys a talent can turn into charges.

    ``Ability_Charge_<X>`` is a plain data value; it does something only because
    Hero_Common has a Modifier Listener naming it, which fires that ability's
    "Set Max Charges" event. Dash, Defensive, Primary, Secondary and Ultimate
    have one. Trait has none, so a modifier of +1 TRAIT charge did nothing
    (user report 2026-10-23); TRAIT charges come from Hero_Common's Trait
    Ability Max Charges Counter instead, raised and lowered by named events
    (:data:`TRAIT_CHARGE_EVENTS`; Merlin's Trait Quest and Snow Queen's Trait
    Charge use them), which ``add_stat`` builds for it. Read from the game's
    files; empty when no game data is reachable."""
    raw = _hero_common()
    if not raw:
        return frozenset()
    names = {n: k for n, k in stat_catalog().items() if n.startswith("Ability_Charge_")}
    heard = [c.body for c in EG.parse(raw).components if c.cls == _LISTENER]
    out = {k for k in names.values() if any(struct.pack("<I", k) in body for body in heard)}
    if _TRAIT_CHARGE in names and _trait_charge_senders(raw):
        out.add(names[_TRAIT_CHARGE])
    return frozenset(out)


#: A TRAIT charge is not a stat: the counter behind TRAIT's max charges is
#: raised by one event and lowered by the other. A talent's owned state fires
#: the first as it switches on and the second as it switches off (the list a
#: state fires on exit is `disables_while_active?`), as Snow Queen's Trait
#: Charge and Merlin's completed Trait Quest do: one charge each.
_TRAIT_CHARGE = "Ability_Charge_Trait"
TRAIT_CHARGE_EVENTS = ("TRAIT_ABILITY_MAX_CHARGES_COUNTER_INC Event Sender",
                       "TRAIT_ABILITY_MAX_CHARGES_COUNTER_DEC Event Sender")


def _hero_common() -> bytes | None:
    from . import corpus
    return next((corpus.read(rel) for rel in corpus.rels("EntitySettings/", _HERO_COMMON)
                 if rel.endswith("/" + _HERO_COMMON)), None)


def _trait_charge_senders(raw: bytes) -> list[tuple[bytes, str]] | None:
    """``(guid, reference label)`` of Hero_Common's TRAIT charge INC and DEC
    senders, or None when the game no longer has both."""
    by_name = {c.name: c for c in EG.parse(raw).components
               if c.cls.endswith("NamedEventSenderSettings")}
    found = [by_name.get(n) for n in TRAIT_CHARGE_EVENTS]
    if not all(found):
        return None
    return [(c.guid, f"[Named Event Sender] Hero_Common\\{c.group}\\{c.name}") for c in found]


_HERO_COMMON = "Hero_Common.entity.ot.EntitySettingsResource.gen"
_LISTENER = "oCEntityCpntModifierListenerSettings"


@dataclass(frozen=True)
class AddedStat:
    selector: str      # the new selector's component name
    modifier: str      # the new modifier's component name ("" for a TRAIT charge)
    slot: int | None   # the card text's {N} for the new number, None without a card format


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

    The controller's owned-state reference moves to a new, empty state (its
    header as the original's), so the original never switches on: whatever the talent
    did hangs off that state, or tests it. What the talent then does is only
    what is added to it (``add_stat``)."""
    graph = EG.parse(raw)
    ctl = next((c for c in graph.components if c.name == f"Skill Controller {talent}"), None)
    if ctl is None:
        raise AddStatError(f"no talent {talent!r} here (no 'Skill Controller {talent}')")
    if any(c.name == rebuilt_name(talent) for c in graph.components):
        raise AddStatError(f"talent {talent!r} is already rebuilt")
    state = owned_state(graph, ctl, talent)
    _c, _s, fmt = card_parts(graph, talent)

    ef = GE.EntityFile(raw)
    try:
        new = rebuilt_name(talent)
        # Written, not cloned: a clone of the state also had to place the
        # sub-objects around it, and failed on Beowulf's and Kintaro's files.
        TW.TalentWriter(ef, (seed or talent) + ":rebuild", state.group).state(
            new, flags=_flags_of(ef, state.name), mode=_mode_of(state))
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
    except (GE.EntityEditError, P.PartError) as e:
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
    # Pickers resolve by PATH, so a child file that defines a node under one of
    # the talent's own names replaces that node rather than reading it: Update 6
    # (2026-10-12) retunes talents this way, e.g. Hero_SunWukong_Update6 carries
    # its own `Skill Power Hold AP Selector`. Same for an explicit override record.
    own_names = {by_guid[x].name for x in seen}
    for g in [graph, *(b if isinstance(b, EG.EntityGraph) else EG.parse(b) for b in readers)]:
        for c in g.components:
            if c.guid in seen or c.guid == ctl.guid or c.name.startswith("Skill Controller ") \
                    or c.cls.endswith("StringFormatValueSettings"):
                continue
            if c.name in own_names or (c.override is not None and c.override.guid in mine):
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


def add_stat(raw: bytes, *, talent: str, stat: str | int, values, percent: bool = True,
             seed: str = "", during: str | None = None, after: str | None = None,
             seconds: float | None = None, cooldown: float | None = None,
             next_ability: str | None = None, on: str | None = None) -> tuple[bytes, AddedStat]:
    """Return ``raw`` (the hero entity holding ``talent``) with the stat bonus added.

    Every part is written (``talent_writer``); nothing is read from another
    hero. The talent needs only its controller, its owned state and (for the
    card's ``{N}``) its description format: the per-rarity number is a new
    selector keyed on the controller, so a talent with no decimal number of
    its own (or a rebuilt one) takes a stat too.

    ``during`` (an ability, e.g. ``"DEFENSE"``) makes the bonus apply only while
    that ability is in use: the modifier's amount reads "ability state active ->
    the per-rarity number, else 0".

    ``after`` (an ability) with ``seconds`` makes it apply for that long each
    time the ability is used, restarting on every use: the ability switches a
    window state on (off and on again if it already was) and the window's timer
    ends it; read through the same selector as ``during``.

    ``on`` (a game event, :data:`TRIGGERS`, e.g. ``"damage_taken"``) with
    ``seconds`` starts the same window from that event instead of an ability: a
    listener held by the talent's owned state fires the restart, as Romeo's
    Panache listens for damage and Wukong's Passive Reveal for day and night.
    ``cooldown`` and ``next_ability`` work with it as with ``after``.

    ``cooldown`` (with ``after`` or ``on``) lets the ability restart the window at most
    once every that many seconds, counted from the restart: Romeo's Love Shield
    gate (:func:`_add_limiter`).

    ``next_ability`` (with ``after``) makes the bonus last only until ability ``next``
    is next used: "within N s after DEFENSE, your next ATTACK ...". When that
    ability's state ENDS, a second restart event switches the window off, so
    the bonus covers that whole use and is gone after it. The list a state fires
    on exit is ``disables_while_active?`` (named before this was known):
    DEFENSE's "Just Exit Timer", the dash's "Exit Event Sender" and Romeo's Love
    Shield cooldown, which starts as the shield ends, all sit there (survey
    2026-10-08)."""
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
    if is_charge(key):
        heard = charges_heard()
        if heard and key not in heard:
            raise AddStatError(
                f"{stat_name(key)!r}: the game never turns it into charges (no ability "
                f"listens for it); charges work for "
                f"{', '.join(sorted(stat_name(k) for k in heard))}")
        if any(v != int(v) for v in amounts.values()):
            raise AddStatError(f"{stat_name(key)!r} counts charges: give whole numbers, "
                               f"got {list(amounts.values())}")
    trait_charge = stat_name(key) == _TRAIT_CHARGE
    if trait_charge:
        if during or after or on:
            raise AddStatError("a TRAIT charge lasts as long as the talent is owned; "
                               "'during', 'after' and 'on' do not apply to it")
        if set(amounts.values()) != {1.0}:
            raise AddStatError("TRAIT charges come one per talent (as Merlin's and Snow "
                               f"Queen's give them): give 1 at every rarity, got "
                               f"{list(amounts.values())}")

    graph = EG.parse(raw)
    ctl, state, fmt = card_parts(graph, talent)

    tag = f"{key:08x}"
    cond_state = None
    hook = None
    if sum(bool(x) for x in (during, after, on)) > 1:
        raise AddStatError("give one of 'during', 'after' or 'on', not several")
    if during:
        cond_state = ability_state(graph, during)
        tag += f" During {during.upper()}"
    starter = "after" if after else "on" if on else None
    if starter and (not isinstance(seconds, int | float) or isinstance(seconds, bool)
                    or seconds <= 0):
        raise AddStatError(f"'{starter}' needs how many seconds it lasts, got {seconds!r}")
    if after:
        hook = ability_state(graph, after, momentary_ok=True)
        tag += f" After {after.upper()}"
    if on:
        if on not in TRIGGERS:
            raise AddStatError(f"on = {on!r}: one of {', '.join(TRIGGERS)}")
        tag += f" On {on}"
    used_up = None
    if next_ability is not None:
        if not starter:
            raise AddStatError("'next' ends an 'after' or 'on' window when that ability is "
                               "used; give 'after' or 'on' too")
        if after and next_ability.upper() == after.upper():
            raise AddStatError(f"'next' is {next_ability.upper()}, the ability that starts the "
                               "window; the bonus would only ever cover that same use")
        # The window must last the whole use, so a state that only flicks on as
        # the ability starts (Merlin) would end it before anything lands.
        used_up = ability_state(graph, next_ability)
        tag += f" Next {next_ability.upper()}"
    if cooldown is not None:
        if not starter:
            raise AddStatError("'cooldown' limits how often 'after' or 'on' restarts; "
                               "give 'after' or 'on' too")
        if not isinstance(cooldown, int | float) or isinstance(cooldown, bool) or cooldown <= 0:
            raise AddStatError(f"'cooldown' needs a number of seconds above 0, got {cooldown!r}")
    new_sel = f"Skill {talent} Added {tag} Selector"
    new_mod = f"Skill {talent} Added {tag} Modifier"
    new_cond = f"Skill {talent} Added {tag} Condition Selector"
    new_win = f"Skill {talent} Added {tag} Window"
    new_timer = f"Skill {talent} Added {tag} Window Timer"
    new_restart = f"Event Skill {talent} Added {tag} Window Restart"
    new_consume = f"Event Skill {talent} Added {tag} Window Used Up"
    if any(c.name in (new_sel, new_mod) for c in graph.components):
        raise AddStatError(f"talent {talent!r} already gets this stat from an earlier entry")

    ef = GE.EntityFile(raw)
    # The tag is always part of it: two stats on one talent would otherwise
    # mint the same GUIDs, and so would one stat on two talents of a block.
    seed = f"{seed}:{talent}:{tag}" if seed else f"{talent}:{tag}"
    w = TW.TalentWriter(ef, seed, f"Skill {talent}")
    try:
        number = w.rarity(new_sel, TW.link_to(ef, ctl.name), amounts)
        amount = number
        if starter:
            # The window: a state the ability switches off and on again (the
            # restart event); its timer's `state` ENDS it when `seconds` run
            # out. A timer's `state` never switches a state on (playtest
            # 2026-10-06: pointing only the timer at the window, the window
            # never came on); this is Beowulf's Damage Aura shape (proc event
            # -> state, state -> timer).
            win = w.link(new_win, TW._STATE, w.group)
            timer = w.timer(new_timer, float(seconds), win)
            w.state(new_win, while_active=[timer], flags=_flags_of(ef, state.name),
                    mode=_mode_of(state))
            restart = w.state(new_restart, activates=[win], deactivates=[win])
            if used_up is not None:
                # A restart event that only switches the window off, fired as
                # `next`'s ability ends.
                w.state(new_consume, deactivates=[win])
                ef.add_ref(used_up.name, "disables_while_active?", new_consume)
            fires, fires_name = restart, new_restart
            if cooldown is not None:
                fires_name = _add_limiter(w, owned=state.name, restart=restart,
                                          seconds=float(cooldown),
                                          tag=f"Skill {talent} Added {tag}")
                fires = w.link(fires_name, TW._TESTER, w.group)
            if hook is not None:
                ef.add_ref(hook.name, "activates", fires_name)
            else:
                # No hero-is-alive check: Romeo's Panache listens without one.
                from .item_effect import add_listener
                listener = add_listener(w, on, f" Skill {talent} Added {tag}", fires,
                                        alive=False, group=w.group)
                ef.add_ref(state.name, "while_active", listener)
            cond_state = win
        elif cond_state is not None:
            cond_state = TW.link_to(ef, cond_state.name)
        if cond_state is not None:
            amount = w.when(new_cond, cond_state, number)      # else 0
        if trait_charge:
            # Not a modifier: +1 on the counter as the talent's state comes on,
            # -1 as it goes off. The number above is only the card's.
            senders = _trait_charge_senders(_hero_common() or b"")
            if senders is None:
                raise AddStatError("Hero_Common no longer has the TRAIT charge events")
            (inc, inc_label), (dec, dec_label) = senders
            ef.add_external_ref(state.name, "activates", inc, inc_label)
            ef.add_external_ref(state.name, "disables_while_active?", dec, dec_label)
            new_mod = ""
        else:
            w.modifier(new_mod, key, amount)
            ef.add_ref(state.name, "while_active", new_mod)
        slot = ef.add_format_slot(fmt.name, new_sel, percent=percent) if fmt else None
        out = ef.to_bytes()
    except (GE.EntityEditError, P.PartError) as e:
        raise AddStatError(f"talent {talent!r}: {e}") from e
    return out, AddedStat(new_sel, new_mod, slot)


def card_parts(graph: EG.EntityGraph, talent: str) -> tuple[EG.Component, EG.Component,
                                                              EG.Component | None]:
    """``(controller, owned state, card description format)`` of a talent: all
    a talent needs to take written parts."""
    ctl = next((c for c in graph.components if c.name == f"Skill Controller {talent}"), None)
    if ctl is None:
        raise AddStatError(f"no talent {talent!r} here (no 'Skill Controller {talent}')")
    state = owned_state(graph, ctl, talent)
    # A card with rarities has numbers keyed on them; one with none (an
    # ultimate) would show only the Common number, whatever was asked for.
    if not any(c.cls.endswith("ValueSelectorSettings") and any(r.guid == ctl.guid for r in c.refs)
               for c in graph.components):
        raise AddStatError(f"talent {talent!r} has no per-rarity number, so its card has "
                           "no rarity a new number could scale with (ultimates are like this)")
    by_guid = graph.by_guid()
    fmts = [by_guid[r.guid] for r in ctl.refs if r.guid in by_guid
            and by_guid[r.guid].cls.endswith("StringFormatValueSettings")]
    fmt = next((c for c in fmts if "Desc" in c.name), fmts[-1] if fmts else None)
    return ctl, state, fmt


def _mode_of(c: EG.Component) -> int:
    return struct.unpack_from("<I", c.body, 2)[0]


def _flags_of(ef: GE.EntityFile, name: str) -> int:
    c = ef.component(name)
    p = ef.objects[c.index - 1]
    head = len(p) - len(c.body)
    return struct.unpack_from("<I", p, head - 8 - len(c.group.encode("latin-1")))[0]


def _add_limiter(w: TW.TalentWriter, *, owned: str, restart: P.Link,
                 seconds: float, tag: str) -> str:
    """A gate firing ``restart`` at most once every ``seconds``; the name of its
    tester, which the starter (an ability's state, a listener) fires.

    Romeo's Love Shield gate: the starter fires a tester that passes only while
    Available is on and Active is off, and switches Active on; Active starts
    its timer (which ENDS Active after ``seconds``: the gate reopens) and the
    restart. Available is on while the talent is owned."""
    names = (f"{tag} Cooldown Tester", f"{tag} Cooldown", f"{tag} Cooldown Timer",
             f"{tag} Cooldown Available")
    on = w.link(names[1], TW._STATE, w.group)
    timer = w.timer(names[2], seconds, on)
    w.state(names[1], activates=[timer, restart], flags=0x1, mode=2)
    ready = w.state(names[3], flags=0x1)
    w.gate(names[0], on=ready, off=on, then=on)
    w.ef.add_ref(owned, "while_active", names[3])
    return names[0]


def stat_key_bytes(stat: str | int) -> bytes:
    """The 4 bytes a modifier stores for ``stat`` (tests and diagnostics)."""
    return struct.pack("<I", resolve_stat(stat))
