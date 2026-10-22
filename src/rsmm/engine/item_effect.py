"""An item's ``effect``: "on <trigger>, gain <amount> <stat> for <seconds> s".

Compiled from the recipe proven in game on Little Thumb Pebbles (2026-10-20:
three hits, three exact 5.0 s windows, no stacking), so it works on ANY base
item rather than on one base's part names:

* the timed bonus is Dash_Crit_Chance's: a tester, kept running by the item's
  equipped state, holds a modifier on while a timer has time left. A modifier
  on a state's ``while_active`` lasted ~1.5 s in game, so that shape is not used;
* the trigger is the listener of a shipped item that reacts to it, copied and
  pointed at a fresh trigger state (a copy of Dash_Crit_Chance's emptied
  ``On Dash Event``) that restarts the timer (off, then on), so every trigger
  refreshes the full duration. Each trigger is one some shipped item listens
  for (surveyed 2026-10-20: 23 listeners, 19 distinct); see ``TRIGGERS`` for
  which are proven in game;
* the base's own stat effects are cut unless ``keep_base_effect`` (the base is
  the item's look, not its behaviour);
* the card's ``{0}`` is the amount and ``{1}`` the seconds, so the card always
  says what the effect does.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import entity_check as CK
from . import entity_fields as EF
from . import item_modifier as IM
from .entity_graph_edit import EntityEditError, EntityFile

_DASH = "Objects\\Magical_Objects\\Common\\Dash_Crit_Chance.entity.ot"
_SHIELD = "Objects\\Magical_Objects\\Rare\\Increase_Shield.entity.ot"

#: The timed bonus: (tester, timer, modifier, seconds value, amount value).
_TIMED = ("Crit Chance Modifier Active Tester", "Crit Chance Modifier Timer",
          "Crit Chance Modifier", "Crit Chance Duration Value", "Crit Chance Value")


@dataclass(frozen=True)
class Trigger:
    donor: str                # a shipped item that listens for it
    listener: str             # its listener: the part copied
    text: str                 # what the card says, for the editor
    via: tuple[str, ...] = () # parts the listener goes through, copied along
    target: str = ""          # the part that switched the donor's state on
                              # (default: the listener itself)


def _mo(rarity: str, item: str) -> str:
    return f"Objects\\Magical_Objects\\{rarity}\\{item}.entity.ot"


#: Every trigger a shipped item's listener reacts to, with that item as donor.
#: The ability-used event is one listener filtered by flags (Dash / Special /
#: Defense / Ultimate / Power), so those five share its proven mechanism.
#: PROVEN in game 2026-10-20 (effect-triggers-test): damage_taken, dash,
#: special, defense, power, talent_picked, item_picked_up,
#: dream_shards_gained, night_start. Not yet exercised: ultimate, day_start,
#: sandman_purchase, reroll.
#: No "hit": Passive_Heal's CHARACTER_HAS_BEEN_HIT is sent by Character_Common
#: with no targets and the world flag off (mode 0), so it reaches no one
#: (sender FUN_140780390); it never fired in 18 hits. Use damage_taken.
TRIGGERS = {
    "damage_taken": Trigger(_SHIELD, "On Damage Received Event Listener",
                            "After taking damage",
                            # the tester reads the hero's health ratio from its own item
                            via=("Hero Is Alive Tester", "Entity Get Ration Health Hero Value"),
                            target="Hero Is Alive Tester"),
    "dash": Trigger(_DASH, "On Dash Event Listener", "After dashing"),
    "special": Trigger(_mo("Epic", "Secondary_Gain_Charge"), "Special Event Listener",
                       "After using your special"),
    "defense": Trigger(_mo("Legendary", "Defense_Heal"), "Defense Use Event Listener",
                       "After using your defense"),
    "ultimate": Trigger(_mo("Epic", "Reduce_Ultimate_CD"), "Ultimate Used Event Listener",
                        "After using your ultimate"),
    "power": Trigger(_mo("Legendary", "Clear_Dash_Cooldown_On_Defense"),
                     "Use Power Game Event Listener", "After using your power"),
    "day_start": Trigger(_mo("Legendary", "Full_Heal_At_Day_Night"), "Day Event Listener",
                         "When day begins"),
    "night_start": Trigger(_mo("Legendary", "Full_Heal_At_Day_Night"), "Night Event Listener",
                           "When night begins"),
    "talent_picked": Trigger(_mo("Legendary", "Upgrade_All_Talents_Once"),
                             "Skill Selected Game Event Listener", "After picking a talent"),
    "item_picked_up": Trigger(_mo("Cursed", "Destroy_Legendary_To_Damage"),
                              "On Magical Object Pick Up Event Listener",
                              "After picking up a magical object"),
    "dream_shards_gained": Trigger(_mo("Cursed", "Curse_Stack_Shard_Quest"),
                                   "Gain Dream Shards Event Listener",
                                   "After gaining dream shards"),
    "sandman_purchase": Trigger(_mo("Common", "Reduce_Dream_Shard_Price"),
                                "Sandman Purchase Event Listener",
                                "After buying from the Sandman"),
    "reroll": Trigger(_mo("Common", "Reroll_To_Dream_Shards"), "Reroll From Code Event Listener",
                      "After a reroll"),
}
#: The trigger state every listener is pointed at: emptied, it only restarts
#: the effect's timer.
_TRIGGER_STATE = "On Dash Event"
_LISTENER_TARGETS = ("ref_3", "ref_4", "ref_5", "on_event")

SUFFIX = " Effect"
_EQUIPPED = "Child State Equiped"          # sic: the model's spelling
_MODIFIER = "oCEntityCpntModifierSettings"
_DESCRIPTION = "Descripton Format"          # sic


class ItemEffectError(ValueError):
    pass


@dataclass(frozen=True)
class Effect:
    """One effect. Without ``seconds`` it is ALWAYS ON while the item is held
    (a plain stat item's shape: a modifier on the equipped state's
    ``while_active``); with ``seconds`` it is a timed bonus after ``on``."""
    stat: str
    amount: float
    seconds: float | None = None
    on: str | None = None
    refresh: bool = True
    percent: bool = True        # the card shows the amount x100 with a %
    keep_base_effect: bool = False

    @property
    def timed(self) -> bool:
        return self.seconds is not None

    @classmethod
    def parse(cls, raw) -> Effect:
        """An ``effect`` table from a manifest, checked."""
        if not isinstance(raw, dict):
            raise ItemEffectError("effect must be a table: { stat, amount } or "
                                  "{ stat, amount, seconds, on }")
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ItemEffectError(f"effect has no field {', '.join(sorted(unknown))}")
        for k in ("stat", "amount"):
            if k not in raw:
                raise ItemEffectError(f"effect needs {k!r}")
        try:
            IM.resolve_stat(raw["stat"])
        except IM.ItemModifierError as e:
            raise ItemEffectError(f"effect stat: {e}") from None
        timed = "seconds" in raw or "on" in raw
        if timed and "seconds" not in raw:
            raise ItemEffectError("effect: a trigger ('on') needs 'seconds' (how long the "
                                  "bonus lasts); leave both out for an always-on bonus")
        on = str(raw.get("on", "damage_taken")) if timed else None
        if on is not None and on not in TRIGGERS:
            raise ItemEffectError(f"effect on = {on!r}: one of {', '.join(TRIGGERS)}")
        for k in ("amount", "seconds"):
            if k in raw and (isinstance(raw[k], bool) or not isinstance(raw[k], (int, float))):
                raise ItemEffectError(f"effect {k} must be a number")
        if timed and raw["seconds"] <= 0:
            raise ItemEffectError("effect seconds must be above 0")
        for k in ("refresh", "percent", "keep_base_effect"):
            if k in raw and not isinstance(raw[k], bool):
                raise ItemEffectError(f"effect {k} must be true or false")
        return cls(stat=str(raw["stat"]), amount=float(raw["amount"]),
                   seconds=float(raw["seconds"]) if timed else None, on=on,
                   refresh=raw.get("refresh", True), percent=raw.get("percent", True),
                   keep_base_effect=raw.get("keep_base_effect", False))


def parse_effects(raw) -> list[Effect]:
    """An ``effects`` list from a manifest (or one ``effect`` table), checked."""
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ItemEffectError("effects must be a list of effect tables")
    out = []
    for i, r in enumerate(raw, 1):
        try:
            out.append(Effect.parse(r))
        except ItemEffectError as e:
            raise ItemEffectError(f"effects[{i}]: {e}") from None
    return out


def _suffix(i: int) -> str:
    """Part-name suffix of the ``i``-th effect: the first keeps the name a lone
    `effect` always had."""
    return SUFFIX if i == 0 else f"{SUFFIX} {i + 1}"


def apply_effect(ent: bytes, item_id: str, effect: Effect, *, read=None) -> bytes:
    """``ent`` (an item entity, already renamed to ``item_id``) doing ``effect``."""
    return apply_effects(ent, item_id, [effect], read=read)


def apply_effects(ent: bytes, item_id: str, effects: list[Effect], *, read=None) -> bytes:
    """``ent`` (an item entity, already renamed to ``item_id``) doing every one
    of ``effects``. The card's ``{0}``, ``{1}``... are each effect's numbers in
    order: an always-on effect's amount, a timed one's amount then seconds. The
    item icon counts the first timed effect down."""
    read = read or CK._corpus_reader
    ef = EntityFile(ent, item_id)
    slots: list[tuple[str, bool]] = []
    mods: list[tuple[str, str]] = []
    first_timer = None
    try:
        equipped = _equipped_state(ef)
        if not any(e.keep_base_effect for e in effects):
            _cut_base(ef, ent)
        for i, effect in enumerate(effects):
            sfx = _suffix(i)
            if effect.timed:
                timer, mod = _add_timed(ef, item_id, effect, sfx, equipped, read, slots)
                first_timer = first_timer or (timer, effect.seconds)
            else:
                mod = _add_passive(ef, item_id, effect, sfx, equipped, read, slots)
            mods.append((mod, effect.stat))
        _card_slots(ef, slots)
        if first_timer is not None:
            _cooldown_display(ef, *first_timer)
    except EntityEditError as e:
        raise ItemEffectError(f"effect: {e}") from e
    out = ef.to_bytes()
    for mod, stat in mods:
        try:
            out = IM.set_modifier_stat(out, mod, stat)
        except IM.ItemModifierError as e:
            raise ItemEffectError(f"effect stat: {e}") from e
    return out


#: An always-on bonus: (modifier, amount value) of the same donor.
_PASSIVE = ("Crit Chance Modifier", "Crit Chance Value")


def _add_passive(ef: EntityFile, item_id: str, effect: Effect, sfx: str, equipped: str,
                 read, slots: list) -> str:
    """A modifier held on while the item is equipped, as a plain stat item's."""
    mod, amount = (n + sfx for n in _PASSIVE)
    ef.clone(list(_PASSIVE), rename={n: n + sfx for n in _PASSIVE},
             seed=f"effect:{item_id}:passive{sfx}", source=_donor(_DASH, read))
    ef.set_value(mod, "amount", effect.amount)        # inline, see _add_timed
    ef.set_value(amount, "value", effect.amount)
    ef.add_ref(equipped, "while_active", mod)
    slots.append((amount, effect.percent))
    return mod


def _add_timed(ef: EntityFile, item_id: str, effect: Effect, sfx: str, equipped: str,
               read, slots: list) -> tuple[str, str]:
    tester, timer, mod, seconds, amount = (n + sfx for n in _TIMED)
    seed = "" if sfx == SUFFIX else sfx
    ef.clone(list(_TIMED), rename={n: n + sfx for n in _TIMED},
             seed=f"effect:{item_id}:timed{seed}", source=_donor(_DASH, read))
    # The modifier and timer carry their numbers INLINE. Linked to the copied
    # Value parts they read the donor's inline numbers instead (0.05 and 3 s
    # for every trigger, playtest 2026-10-20), while links to an item's own
    # Values work (Pebbles' Shield Value). The copied Values stay only for
    # the card's numbers.
    ef.set_value(mod, "amount", effect.amount)
    ef.set_value(timer, "duration", effect.seconds)
    ef.set_value(amount, "value", effect.amount)
    ef.set_value(seconds, "value", effect.seconds)

    trig = TRIGGERS[effect.on]
    state = "On Trigger" + sfx
    ef.clone([_TRIGGER_STATE], rename={_TRIGGER_STATE: state},
             seed=f"effect:{item_id}:state{seed}", source=_donor(_DASH, read))
    for field in ("activates", "deactivates?"):     # the donor's own effect
        while _items(ef, state, field):
            ef.remove_ref(state, field, 0)
    if effect.refresh:                               # off, then on: full time again
        ef.add_ref(state, "deactivates?", timer)
    ef.add_ref(state, "activates", timer)
    parts = (trig.listener, *trig.via)
    ef.clone(list(parts), rename={n: n + sfx for n in parts},
             seed=f"effect:{item_id}:{effect.on}{seed}", source=_donor(trig.donor, read))
    # Whatever the listener (or the part it goes through) switched on in
    # the donor, it switches on the trigger state now.
    _retarget(ef, (trig.target or trig.listener) + sfx, state)
    ef.add_ref(equipped, "while_active", trig.listener + sfx)
    ef.add_ref(equipped, "while_active", tester)
    slots += [(amount, effect.percent), (seconds, False)]
    return timer, mod


def describe(effects: list[Effect]) -> str:
    """Card text for ``effects``, numbered as `apply_effects` lays out the card:
    "#+{0}%@ #Crit chance@" for an always-on bonus, "After dashing, gain
    #+{1}%@ #Attack power@ for #{2}@ seconds" for a timed one. One bullet each, as
    the shipped cards write several effects."""
    lines, n = [], 0
    for e in effects:
        amount = f"#+{{{n}}}{'%' if e.percent else ''}@ #{e.stat}@"
        if e.timed:
            lines.append(f"{TRIGGERS[e.on].text}, gain {amount} for #{{{n + 1}}}@ seconds")
            n += 2
        else:
            lines.append(amount)
            n += 1
    return "\n".join("• " + line for line in lines)


def donor_stems(effects: Effect | list[Effect]) -> set[str]:
    """Entities the effects copy parts from (for the leftover-link check)."""
    if isinstance(effects, Effect):
        effects = [effects]
    return {_stem(_DASH)} | {_stem(TRIGGERS[e.on].donor) for e in effects if e.timed}


def trigger_texts() -> dict[str, str]:
    """``{on: card wording}`` for the editor's trigger picker."""
    return {k: t.text for k, t in TRIGGERS.items()}


def _stem(ref: str) -> str:
    return ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")


def _donor(ref: str, read) -> EntityFile:
    raw = read(ref)
    if raw is None:
        raise ItemEffectError(f"effect: the shipped {_stem(ref)} is not readable "
                              f"(no install or mirror)")
    return EntityFile(raw, _stem(ref))


def _retarget(ef: EntityFile, comp: str, state: str) -> None:
    """Point each target ``comp`` had in its donor at ``state``: a listener's
    ``ref_3``..``ref_5`` / ``on_event``, or a tester's ``on_true``."""
    fields = {f.name: f for f in EF.fields(ef.component(comp))}
    names = [n for n in (*_LISTENER_TARGETS, "on_true") if n in fields
             and fields[n].text and "<-" in fields[n].text]
    if not names:
        raise ItemEffectError(f"effect: {comp!r} has no target to point at the trigger")
    for n in names:
        ef.set_ref(comp, n, state)


def _items(ef: EntityFile, comp: str, field: str) -> list:
    f = next((x for x in EF.fields(ef.component(comp)) if x.name == field), None)
    return f.items if f is not None else []


def _equipped_state(ef: EntityFile) -> str:
    """The item's equipped state: its override of the model's, which runs while
    the hero holds the item (both donors keep their listener and tester there)."""
    for c in ef.graph().components:
        if c.override is not None and c.override.path.endswith("\\" + _EQUIPPED):
            return c.name
    raise ItemEffectError("effect: this base has no equipped state to run the effect from")


_LISTENERS = ("oCGameEventListenerEntityCpntSettings",
              "oCEntityCpntNamedEventListenerSettings")
_SUPER_STATE = "Child State Super Effect"


def _cut_base(ef: EntityFile, ent: bytes) -> None:
    """Unlink the base's own effect, so the copy stops doing what the base did:
    every modifier but the super effect's, and every listener that is not the
    super effect's. Cutting only the modifiers left a shield copy's damage
    listener running its 30 s reload, which the item's cooldown display reads:
    14 shield copies all showed a cooldown after any hit (playtest 2026-10-20)."""
    own = {m.name for m in IM.list_modifiers(ent) if not m.super_effect}
    try:
        keep = {i.text.rstrip().rsplit("\\", 1)[-1]
                for f in EF.fields(ef.component(_SUPER_STATE)) if f.kind == "ref[]"
                for i in f.items}
    except EntityEditError:
        keep = set()
    own |= {c.name for c in ef.graph().components
            if c.cls in _LISTENERS and c.name not in keep}
    for c in ef.graph().components:
        for f in EF.fields(c):
            if f.kind == "ref[]":
                for i in reversed(range(len(f.items))):
                    if f.items[i].text.rstrip().rsplit("\\", 1)[-1] in own:
                        ef.remove_ref(c.name, f.name, i)
            elif f.kind == "ref" and f.text and f.text.rstrip().rsplit("\\", 1)[-1] in own:
                ef.set_ref(c.name, f.name, None)


_ITEM_DATA = "Dt Magical Object Data"


def _cooldown_display(ef: EntityFile, timer: str, seconds: float) -> None:
    """Make the item icon count the effect down, wired as the one shipped item
    whose countdown works (Curse_Lose_Life_Gain_Damage; RE 2026-10-20,
    docs/_re/kinds/items.md): the item data's ``value_4`` is the full time and
    ``value_5`` the timer's ELAPSED time; the item is in cooldown while
    ``value_5 / value_4 < 1``. Increase_Shield, Defense_Heal and Gain_
    Regeneration read their timer with 0x0fd2c964, a key no Timer answers, so
    copying their link left the countdown dead. The full time is written
    inline, and the timer link replaces whatever the slot held."""
    ef.set_value(_ITEM_DATA, "value_4", seconds)
    c = ef.component(_ITEM_DATA)
    f = next(x for x in EF.fields(c) if x.name == "value_5")
    n = next(i for i, v in enumerate(ef._value_pickers(c))
             if f.offset <= v.offset < f.offset + f.size)
    ef.source_value(_ITEM_DATA, n, timer, accessor=EntityFile.TIMER_ELAPSED)


def _card_slots(ef: EntityFile, slots: list[tuple[str, bool]]) -> None:
    """Make the description's ``{0}``, ``{1}``... the given Values, in order. The
    new slots are copies of an existing one, so they are added before the
    base's own are dropped."""
    c = ef.component(_DESCRIPTION)
    old = len(ef._format_slots(c)[0])
    for n, (value, percent) in enumerate(slots):
        try:
            ef.add_format_slot(_DESCRIPTION, value, percent=percent)
        except EntityEditError as e:
            if n or "no String Format slot" not in str(e):
                raise
            raise ItemEffectError("effect: this base's card shows no numbers, so there is "
                                  "no {0} to copy for the amount; pick another base") from None
    if not old:
        return
    c = ef.component(_DESCRIPTION)
    found, count_f = ef._format_slots(c)
    at = len(ef.objects[c.index - 1]) - len(c.body)
    p = ef.objects[c.index - 1]
    del p[at + found[0].offset:at + found[old - 1].offset + found[old - 1].size]
    struct.pack_into("<I", p, at + count_f.offset, len(found) - old)
