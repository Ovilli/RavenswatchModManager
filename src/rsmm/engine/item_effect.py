"""An item's ``effects``: always-on bonuses and "on <trigger>, gain <amount>
<stat> for <seconds> s".

Every part is WRITTEN here from field values (``entity_parts``), not copied out
of a shipped item, so a custom item does not depend on any other item. The
parts are the recipe proven in game on Little Thumb Pebbles (2026-10-20: three
hits, three exact 5.0 s windows, no stacking) and on effect-triggers-test, and
they are byte for byte what copying the proven parts produced
(``tests/test_item_effect_parts.py``):

* an always-on bonus is a modifier on the item's equipped state's
  ``while_active``, as every plain stat item does;
* a timed bonus is a tester, kept running by the equipped state, that holds a
  modifier on while a timer has time left (a modifier on a trigger state's
  ``while_active`` lasted ~1.5 s in game, so that shape is not used);
* a trigger is a game-event listener (``TRIGGERS``: the event and its flag
  filter, as the shipped items listen for it) that switches on a trigger state,
  which restarts the timer (off, then on), so every trigger refreshes the full
  duration;
* the base's own stat effects are cut unless ``keep_base_effect`` (the base is
  the item's look, not its behaviour);
* the card's ``{0}``, ``{1}``... are each effect's numbers, so the card always
  says what the effects do.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from . import entity_fields as EF
from . import entity_parts as P
from . import item_modifier as IM
from .entity_graph_edit import EntityEditError, EntityFile

# The game stores vitality and attack power as fractions and reports them in
# points (100 * the stored value). Effect amounts for these stats use the
# reported points.
_VITALITY = 0x188671A6


def _stat_key(stat: str | int) -> int | None:
    try:
        return IM.resolve_stat(stat)
    except IM.ItemModifierError:
        return None


def _is_attack_power(stat: str | int) -> bool:
    key = _stat_key(stat)
    return key is not None and (IM.stat_name(key) or "").startswith("Attack power")


def _in_points(stat: str | int) -> bool:
    return _stat_key(stat) == _VITALITY or _is_attack_power(stat)


#: Flat stats shipped cards print as the number itself (display mode 0 or 2,
#: never x100): armour 20 reads "+20", not "+2000". Fairy Dust's shield
#: (mode 2) reads "10": Level Healing Selector x 1.0, the game's own points.
_PLAIN = frozenset({"Armour", "Shield", "Regeneration", "Dash Damage", "Clamp High Damage Duration",
                    "Dash Heal For Damage Received Duration"})


def _shows_plain(stat: str | int) -> bool:
    key = _stat_key(stat)
    return key is not None and IM.stat_name(key) in _PLAIN

#: Part names, kept from the recipe the parts were first copied from so a mod's
#: ``steps`` that name them keep working: (tester, timer, modifier, seconds
#: value, amount value, amount x copies operation).
_TIMED = ("Crit Chance Modifier Active Tester", "Crit Chance Modifier Timer",
          "Crit Chance Modifier", "Crit Chance Duration Value", "Crit Chance Value",
          "Crit Chance Value Operation")
_TRIGGER_STATE = "On Trigger"

#: The game event every ability use sends; its flag filter says which ability.
_ABILITY_USED = 0x17d370a7


@dataclass(frozen=True)
class Trigger:
    """A game event an item reacts to, as a shipped item's listener filters it."""
    listener: str             # the listener part's name
    text: str                 # what the card says, for the editor
    event: int                # the game event id
    include: tuple[str, ...] = ()   # flags the event must carry
    exclude: tuple[str, ...] = ()   # flags it must not
    slots: tuple[str, ...] = ("ref_4",)   # which reference(s) it switches on
    flags: int = 0x1000001    # the listener record's header flags
    tail: bytes = bytes(5)    # the listener settings' last five bytes
    target: str = ""          # the part the listener fires, when not the state
                              # (damage_taken: a "hero is alive" check)
    group: str = ""           # the listener's group, as the shipped item files it


#: Every trigger, as the shipped item that reacts to it listens for it.
#: PROVEN in game 2026-10-20 (effect-triggers-test): damage_taken, dash,
#: special, defense, power, talent_picked, item_picked_up,
#: dream_shards_gained, night_start. Not yet exercised: ultimate, day_start,
#: sandman_purchase, reroll.
#: No "hit": Passive_Heal's CHARACTER_HAS_BEEN_HIT is sent by Character_Common
#: with no targets and the world flag off (mode 0), so it reaches no one
#: (sender FUN_140780390); it never fired in 18 hits. Use damage_taken.
TRIGGERS = {
    "damage_taken": Trigger("On Damage Received Event Listener", "After taking damage",
                            0x17df7da0, exclude=("Self",), target="Hero Is Alive Tester"),
    "dash": Trigger("On Dash Event Listener", "After dashing", _ABILITY_USED,
                    ("Dash",), ("NotADash",), flags=0x1000101),
    "special": Trigger("Special Event Listener", "After using your special", _ABILITY_USED,
                       ("Special",), ("NotAAbility",)),
    "defense": Trigger("Defense Use Event Listener", "After using your defense",
                       _ABILITY_USED, ("Defense",), ("NotAAbility",), flags=0x1),
    "ultimate": Trigger("Ultimate Used Event Listener", "After using your ultimate",
                        _ABILITY_USED, ("Ultimate",)),
    "power": Trigger("Use Power Game Event Listener", "After using your power",
                     _ABILITY_USED, ("Power",), ("NotAAbility",)),
    "day_start": Trigger("Day Event Listener", "When day begins", 0x17d8d8fa, flags=0x1),
    "night_start": Trigger("Night Event Listener", "When night begins", 0x17d8d8fc, flags=0x1),
    "talent_picked": Trigger("Skill Selected Game Event Listener", "After picking a talent",
                             0x17fc7683, slots=("ref_5",)),
    "item_picked_up": Trigger("On Magical Object Pick Up Event Listener",
                              "After picking up a magical object", 0x1a9cae51,
                              slots=("ref_5",), flags=0x1000101),
    "dream_shards_gained": Trigger("Gain Dream Shards Event Listener",
                                   "After gaining dream shards", 0x12e831f3,
                                   slots=("ref_3", "ref_4"), tail=bytes([2, 0, 0, 0, 0])),
    "sandman_purchase": Trigger("Sandman Purchase Event Listener",
                                "After buying from the Sandman", 0x1a18fd13),
    "reroll": Trigger("Reroll From Code Event Listener", "After a reroll", 0x1a9b21a4,
                      slots=("ref_4", "ref_5"), flags=0x1, group="Reroll From Code"),
}

#: Continuous day/night conditions: global bool keys read by Character_Common's
#: "Is Daytime Tester" and "Is Nighttime Tester" (which hold State Daytime and
#: State Nighttime on for Scarlet and Piper).
_IS_DAYTIME, _IS_NIGHTTIME = 0x17d8d89b, 0x17d8d89c
DURING = {
    "day": ("Active only during day", "During the day", _IS_DAYTIME),
    "night": ("Active only during night", "During the night", _IS_NIGHTTIME),
}

#: Accessor keys a value picker reads another part through (``items.md``): a
#: Timer's time left, a listener's "fired", a GetValue's value.
_TIMER_LEFT, _LISTENER_FIRED, _GOT_VALUE = 0x16831980, 0x12e4a37e, 0x16abf2eb
#: Where damage_taken's "hero is alive" check reads the hero's health from.
_HERO = ("EntitySettings", "Heroes\\Hero_Common\\Hero_Common.entity.ot")
_HEALTH = ("Character_Common\\Character_Common.entity.ot", "Base\\Health Ratio")

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
    ``while_active``, or gated by ``during``); with ``seconds`` it is a timed
    bonus after ``on``."""
    stat: str
    amount: float | int
    seconds: float | None = None
    on: str | None = None
    during: str | None = None
    refresh: bool = True
    percent: bool = True        # the card shows the amount x100 with a %
    keep_base_effect: bool = False
    per_level: bool = False     # grows with hero level, as Fairy Dust's shield

    @property
    def timed(self) -> bool:
        return self.seconds is not None

    @property
    def modifier_amount(self) -> float | int:
        """The native value written to the game modifier.

        Vitality and attack power are authored in the points shown by the game,
        but their modifiers store a fraction: one point is 0.01.
        """
        return float(self.amount) / 100 if _in_points(self.stat) else self.amount

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
        during = str(raw["during"]) if raw.get("during") is not None else None
        if during is None and "seconds" not in raw and raw.get("on") in DURING:
            during = str(raw["on"])
        if during is not None and during not in DURING:
            raise ItemEffectError(f"effect during = {during!r}: one of {', '.join(DURING)}")
        timed = "seconds" in raw or ("on" in raw and raw.get("on") not in DURING)
        if timed and "seconds" not in raw:
            raise ItemEffectError("effect: a trigger ('on') needs 'seconds' (how long the "
                                  "bonus lasts); leave both out for an always-on bonus")
        on = str(raw.get("on", "damage_taken")) if timed else None
        if on is not None and on not in TRIGGERS:
            raise ItemEffectError(f"effect on = {on!r}: one of {', '.join(TRIGGERS)}")
        for k in ("amount", "seconds"):
            if k in raw and (isinstance(raw[k], bool) or not isinstance(raw[k], (int, float))):
                raise ItemEffectError(f"effect {k} must be a number")
        for k in ("amount", "seconds"):
            if k in raw and not math.isfinite(raw[k]):
                raise ItemEffectError(f"effect {k} must be a finite number")
        if timed and raw["seconds"] <= 0:
            raise ItemEffectError("effect seconds must be above 0")
        for k in ("refresh", "percent", "keep_base_effect", "per_level"):
            if k in raw and not isinstance(raw[k], bool):
                raise ItemEffectError(f"effect {k} must be true or false")
        is_int = IM.is_integer_stat(raw["stat"])
        if is_int and raw["amount"] != int(raw["amount"]):
            raise ItemEffectError(f"effect amount: {raw['stat']} counts whole units, "
                                  f"got {raw['amount']}")
        in_points = _in_points(raw["stat"])
        if raw.get("per_level") and (is_int or in_points):
            raise ItemEffectError(f"effect per_level: {raw['stat']} does not grow with "
                                  "level; use it on flat stats such as Shield or Armour")
        amount = int(raw["amount"]) if is_int else float(raw["amount"])
        percent = raw.get("percent", not (is_int or in_points or _shows_plain(raw["stat"])))
        return cls(stat=str(raw["stat"]), amount=amount,
                   seconds=float(raw["seconds"]) if timed else None, on=on, during=during,
                   refresh=raw.get("refresh", True), percent=percent,
                   keep_base_effect=raw.get("keep_base_effect", False),
                   per_level=raw.get("per_level", False))


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
    order: an always-on effect's amount, a timed one's amount then seconds.
    ``read`` reads a shipped entity (the hero's, for damage_taken's health check)."""
    from . import entity_check as CK
    read = read or CK._corpus_reader
    ef = EntityFile(ent, item_id)
    slots: list[tuple[str, bool]] = []
    try:
        equipped = _equipped_state(ef)
        if not any(e.keep_base_effect for e in effects):
            _cut_base(ef, ent)
        for i, effect in enumerate(effects):
            w = P.PartWriter(ef, f"effect:{item_id}:{i}")
            sfx = _suffix(i)
            if effect.timed:
                _add_timed(w, effect, sfx, equipped, read, slots, scale=True)
            else:
                _add_passive(w, effect, sfx, equipped, slots, scale=True)
        _card_slots(ef, slots)
    except (EntityEditError, P.PartError) as e:
        raise ItemEffectError(f"effect: {e}") from e
    return ef.to_bytes()


#: Part-name suffix of a super effect's parts (" Super Effect", " Super Effect
#: 2"...): the name marks their modifiers as the super effect's
#: (``item_modifier.list_modifiers``), and keeps them apart from ``effects``'.
SUPER_SUFFIX = " Super Effect"
#: The rarities with a super effect, and how many copies of the item switch it
#: on. The model's `Equiped Super Effect Active Condition` holds `State Super
#: Effect` on while the item is equipped and its own amount (Dt Magical Object,
#: key 0x18a38678: the copies held, what `Amount Selector` scales card numbers
#: by) is at least `Super Effect Target Count Operation`: 5 / 4 / 3 by its Is
#: Common / Is Rare / Is Epic tests, minus whatever lowers it. Any other rarity
#: gets 0, and `Has Super Effect Condition` (target > 0) then fails: never on.
#: Different items of one rarity do not count (playtest 2026-10-24: the item
#: plus two other Epics left it off).
SUPER_COPIES = {"Common": 5, "Rare": 4, "Epic": 3}
SUPER_RARITIES = tuple(SUPER_COPIES)
SUPER_RARITIES = ("Common", "Rare", "Epic")


def apply_super_effects(ent: bytes, item_id: str, effects: list[Effect], *,
                        read=None) -> bytes:
    """``ent`` (an item entity, already renamed to ``item_id``) with ``effects``
    as its SUPER effect: what it does once the hero holds enough copies of the
    item (``SUPER_COPIES``), when the model switches the item's ``Child State
    Super Effect`` on. They are built as ``effects`` are, run from that state instead
    of the equipped one, and numbered on the super text (``{0}``, ``{1}``...).
    The base's own super effect is cut. An item without the model's super slots
    (a blank item, a copy of a legendary) gets them, its text read from
    ``<item_id>_SuperEffect``."""
    from . import entity_check as CK
    from . import item_frame as F
    read = read or CK._corpus_reader
    ef = EntityFile(ent, item_id)
    slots: list[tuple[str, bool]] = []
    try:
        state = _override_of(ef, F.SUPER_STATE)
        has_text = _override_of(ef, F.SUPER_FORMAT) is not None
        if state is None or not has_text:
            F.add_super(P.PartWriter(ef, f"super:{item_id}"), read, f"{item_id}_SuperEffect",
                        state=state is None, text=not has_text)
            state = state or F.SUPER_STATE
        f = next(x for x in EF.fields(ef.component(state)) if x.name == "while_active")
        for i in reversed(range(len(f.items))):         # the base's own super effect
            ef.remove_ref(state, "while_active", i)
        ef.clear_format_slots(F.SUPER_FORMAT)
        for i, effect in enumerate(effects):
            w = P.PartWriter(ef, f"super:{item_id}:{i}")
            sfx = SUPER_SUFFIX if i == 0 else f"{SUPER_SUFFIX} {i + 1}"
            if effect.timed:
                _add_timed(w, effect, sfx, state, read, slots)
            else:
                _add_passive(w, effect, sfx, state, slots)
        for value, percent in slots:
            ef.add_format_slot(F.SUPER_FORMAT, value, percent=percent)
    except (EntityEditError, P.PartError, F.FrameError) as e:
        raise ItemEffectError(f"super effect: {e}") from e
    return ef.to_bytes()


def _override_of(ef: EntityFile, model_part: str) -> str | None:
    """The item's part overriding the model's ``model_part``, or None."""
    for c in ef.graph().components:
        if c.override is not None and c.override.path.endswith("\\" + model_part):
            return c.name
    return None


_MOD = "oCEntityCpntModifierSettings"
_VALUE = "oCEntityCpntValueSettings"
_STATE = "oCEntityCpntStateSettings"
_TIMER = "oCEntityCpntTimerSettings"
_TESTER = "oCEntityCpntTesterSettings"
_LISTENER = "oCGameEventListenerEntityCpntSettings"
_GET = "oCEntityCpntGetValueSettings"
_NONE = P.Link()


#: The unit an amount is marked with (``entity_parts.Num.unit``), as on the
#: proven parts.
_RATIO = 2

_OPS = "oCEntityCpntValueOperationsSettings"
_MULTIPLY = 0x17b29be2
_READ_VALUE = EntityFile.F32_ACCESSOR["oCEntityCpntValueSettings"]
_READ_INT = EntityFile.INT_ACCESSOR["oCEntityCpntValueSettings"]
_AMOUNT_SELECTOR = P.Link(bytes.fromhex("ff9e14f8f4505d4890d387548a6c8f81"),
                          r"[Value Selector] Magical_Objects_Model\Amount Selector")


def _value(w: P.PartWriter, name: str, v: float | int, unit: int = 0) -> P.Link:
    val = P.Num.int(int(v)) if isinstance(v, int) else P.Num.f32(v, unit)
    return w.add(_VALUE, name, {"value": val, "flag": 0}, flags=0x101)


def _scalable_operation(w: P.PartWriter, name: str, value_link: P.Link,
                        *, is_int: bool = False, level: P.Link | None = None,
                        copies: bool = True) -> P.Link:
    """``value_link`` x ``Amount Selector``, so duplicate item copies stack: the
    modifier and the card both read it (playtest 2026-10-24: stat and card number
    grew with a second copy, always-on and timed). ``level`` (a Level Healing
    Selector) multiplies in first, as Fairy Dust's Scalable Shield Operation
    does; ``copies = False`` leaves the copy count out (super effects)."""
    def operand(link: P.Link, key: int, num_type: int) -> bytes:
        return struct.pack("<Ii", 0, -1) + P.num_bytes(
            P.Num(num_type, bytes(4), source=link, key=key), w.ci)
    read_key = _READ_INT if is_int else _READ_VALUE
    num_type = P.INT if is_int else P.F32
    ops = [operand(value_link, read_key, num_type)]
    if level is not None:
        ops.insert(0, operand(level, _READ_VALUE, P.F32))
    if copies:
        ops.append(operand(_AMOUNT_SELECTOR, _READ_INT, P.INT))
    node = w.obj("oCEntityCpntNodeSettings",
                 struct.pack("<II", _MULTIPLY, len(ops)) + b"".join(ops))
    return w.add(_OPS, name, {"operations": node}, flags=0x101)


#: Character_Common's Level Healing (10 at level 1), which Fairy Dust, Healing
#: Orbs' shield, Dash_Gain_Charge and Defense_Heal multiply their flat amount by.
_LEVEL_HEALING = P.Link(bytes.fromhex("2182f3495c1f8c4e84009aa173dc1f9a"),
                        r"[Value] Character_Common\Base\Level Healing")
_GOT_VALID = 0x16abf2f3
_LEVEL_ONE = 10.0


def _level_selector(w: P.PartWriter, sfx: str) -> P.Link:
    """The holder's Level Healing, or 10 with no holder (the shop card), written
    as Fairy Dust's Level Healing Selector."""
    template = w.obj("oCResourceWeakRef", b"".join(P._lstr(x) for x in _HERO))
    method = w.obj("EntityCpntMethodPicker", P.link_bytes(_NONE, w.ci) + b"\xff" * 4)
    got = w.add(_GET, "Owner Level Healing Get Value" + sfx, {
        "source": w.ids("oCEntityCollectorSelectorSettings", [_owner(w, 0)]),
        "template": template, "value": _LEVEL_HEALING, "method": method}, flags=0x101)

    def entry(cond: P.Num, value: P.Num) -> bytes:
        return w.obj("oCEntityCpntValueSelectorEntrySettings",
                     P.num_bytes(cond, w.ci) + P.num_bytes(value, w.ci))
    entries = [entry(P.Num(P.BOOL, b"\x00", source=got, key=_GOT_VALID),
                     P.Num(P.F32, bytes(4), source=got, key=_GOT_VALUE)),
               entry(P.Num(P.BOOL, b"\x01"), P.Num.f32(_LEVEL_ONE))]
    body = (struct.pack("<II", 0, len(entries)) + b"".join(entries)
            + b"\x00\x00" + P.num_bytes(P.Num(P.BOOL, b"\x00"), w.ci))
    return w.add("oCEntityCpntValueSelectorSettings", "Level Healing Selector" + sfx,
                 flags=0x101, body=body)


def _owner(w: P.PartWriter, last: int) -> int:
    """A collector of the entity that holds this one (the hero, for an item)."""
    on = w.obj(P.VALUE_PICKER, b"\x00" + w.obj(P.UNION, struct.pack("<II", P.BOOL, 0) + b"\x01"))
    return w.sub("oCOwnerEntityCollectorSettings",
                 on + b"\x00" + w.obj("oCResourceWeakRef", bytes(8)) + bytes([last]))


def _modifier(w: P.PartWriter, name: str, stat: str, amount: float | int,
              source: P.Link | None = None) -> P.Link:
    """A modifier giving ``amount`` of ``stat`` to whoever holds the item."""
    if IM.is_integer_stat(stat):
        key = EntityFile.INT_ACCESSOR[_OPS] if source is not None else None
        num = (P.Num.int(int(amount)) if source is None
               else P.Num(P.INT, struct.pack("<i", int(amount)), 0, source=source, key=key))
    else:
        num = (P.Num.f32(amount, _RATIO) if source is None
               else P.Num(P.F32, struct.pack("<f", amount), _RATIO, source=source,
                         key=EntityFile.F32_ACCESSOR[_OPS]))
    return w.add(_MOD, name, {
        "modifier_id": IM.resolve_stat(stat), "duration": P.Num.f32(0),
        "amount": num,
        "targets": w.ids("oCEntityCollectorSelectorSettings", [_owner(w, 1)]),
        "value_4": P.Num.f32(1), "sources?": w.ids("oCEntityCollectorSelectorSettings", []),
        "id": P.Num.int(0), "flag": 1}, flags=0x1)


def _float_test(w: P.PartWriter, source: P.Link, key: int) -> int:
    """A condition: ``source`` (read through ``key``) is above 0."""
    a = w.obj(P.VALUE_PICKER, b"\x01\x00" + P.link_bytes(source, w.ci) + struct.pack("<I", key)
              + w.obj(P.UNION, struct.pack("<II", P.F32, 0) + bytes(4)))
    b = w.obj(P.VALUE_PICKER, b"\x00" + w.obj(P.UNION, struct.pack("<II", P.F32, 0) + bytes(4)))
    return w.sub("oCEntityCpntFloatTestSettings", a + b + struct.pack("<I", 2))


def _bool_test(w: P.PartWriter, key: int) -> int:
    """A condition: global bool ``key`` is true, as Character_Common's
    Is Daytime Tester and Is Nighttime Tester check it."""
    return w.sub("oCEntityCpntSimpleBoolTestSettings",
                 P.num_bytes(P.Num(P.BOOL, b"\x00", key=key, glob=True), w.ci)
                 + struct.pack("<I", 0))


def _tester(w: P.PartWriter, name: str, tests: list[int], *, every: bool, flags: int,
            on_true: P.Link = _NONE, holds: P.Link = _NONE) -> P.Link:
    """True while ``tests`` hold (all of them when ``every``); switches
    ``on_true`` on and holds ``holds`` on meanwhile."""
    test = w.obj("oCCombinerCpntTestSettings", bytes([0, int(every)])
                 + struct.pack(f"<I{len(tests)}I", len(tests), *tests))
    return w.add(_TESTER, name, {"on_true": on_true, "ref_2": _NONE, "on_false": _NONE,
                                 "ref_4": _NONE, "test": test, "ref_6": holds,
                                 "ref_7": _NONE}, flags=flags)


def _amount_parts(w: P.PartWriter, effect: Effect, mod: str, amount: str, op: str,
                  scale: bool, sfx: str) -> tuple[P.Link, str]:
    """The card's amount Value and the modifier giving it: ``(modifier link,
    card slot node)``. With ``scale`` both multiply by the held-copy count."""
    if effect.per_level:
        # amount is the level-1 number: amount / 10 x Level Healing (10 at level 1).
        base = _value(w, amount, effect.amount / _LEVEL_ONE, _RATIO)
        mod_op = _scalable_operation(w, op, base, level=_level_selector(w, sfx), copies=scale)
        return _modifier(w, mod, effect.stat, effect.amount, source=mod_op), op
    is_int = IM.is_integer_stat(effect.stat)
    amount_link = _value(w, amount, effect.amount, 0 if is_int else _RATIO)
    if not scale:
        return _modifier(w, mod, effect.stat, effect.modifier_amount), amount
    if _in_points(effect.stat):
        # The card keeps the authored points; the modifier reads the stat's
        # native fraction through its own scaled Value.
        modifier_value = _value(w, "Modifier " + amount, effect.modifier_amount, _RATIO)
        mod_op = _scalable_operation(w, "Modifier " + op, modifier_value)
        _scalable_operation(w, op, amount_link)
    else:
        mod_op = _scalable_operation(w, op, amount_link, is_int=is_int)
    return _modifier(w, mod, effect.stat, effect.modifier_amount, source=mod_op), op


def _add_passive(w: P.PartWriter, effect: Effect, sfx: str, equipped: str,
                 slots: list, *, scale: bool = False) -> None:
    """A modifier held on while the item is equipped (or while ``during`` holds)."""
    tester, _timer_n, mod, _seconds_n, amount, op = (n + sfx for n in _TIMED)
    mod_link, slot_node = _amount_parts(w, effect, mod, amount, op, scale, sfx)
    if effect.during:
        _tester(w, tester, [_bool_test(w, DURING[effect.during][2])], every=False,
                flags=0x1, holds=mod_link)
        w.ef.add_ref(equipped, "while_active", tester)
    else:
        w.ef.add_ref(equipped, "while_active", mod)
    slots.append((slot_node, effect.percent))


def _add_timed(w: P.PartWriter, effect: Effect, sfx: str, equipped: str, read,
               slots: list, *, scale: bool = False) -> str:
    tester, timer, mod, seconds, amount, op = (n + sfx for n in _TIMED)
    state = _TRIGGER_STATE + sfx
    # The modifier and timer carry their numbers INLINE: linked to Value parts
    # they read the donor's inline numbers instead (0.05 and 3 s for every
    # trigger, playtest 2026-10-20). The Values are only the card's numbers.
    _value(w, seconds, effect.seconds)
    mod_link, slot_node = _amount_parts(w, effect, mod, amount, op, scale, sfx)
    timer_link = w.add(_TIMER, timer, {
        "bias?": P.Num.f32(0), "count": P.Num.int(1), "on_tick": _NONE, "on_end": _NONE,
        "state": _NONE, "paused?": P.Num(P.BOOL, b"\x00"), "duration": P.Num.f32(effect.seconds),
        "flag": 0, **_timer_tail(w)}, flags=0x1)
    tests = [_float_test(w, timer_link, _TIMER_LEFT)]
    if effect.during:
        tests.append(_bool_test(w, DURING[effect.during][2]))
    _tester(w, tester, tests, every=len(tests) > 1, flags=0x1, holds=mod_link)
    w.add(_STATE, state, {
        "activates": [timer_link], "deactivates?": [timer_link] if effect.refresh else [],
        "list_2": [], "on_exit?": [], "disables_while_active?": [], "on_enter?": [],
        "while_active": []}, flags=0x10001)

    listener = add_listener(w, effect.on, sfx, w.link(state, _STATE), read=read)
    w.ef.add_ref(equipped, "while_active", listener)
    w.ef.add_ref(equipped, "while_active", tester)
    slots += [(slot_node, effect.percent), (seconds, False)]
    return timer


def add_listener(w: P.PartWriter, on: str, sfx: str, fires: P.Link, *, read=None,
                 alive: bool = True, group: str | None = None) -> str:
    """Write the listener for trigger ``on`` (``TRIGGERS``), firing ``fires``;
    its name. It listens only while a state holding it in ``while_active`` is on
    (the item's equipped state, a talent's owned state). ``alive`` keeps
    damage_taken's "hero is alive" check, as Increase_Shield has it (a talent
    leaves it out, as Romeo's Panache does)."""
    trig = TRIGGERS[on]
    listener = trig.listener + sfx
    if trig.target and alive:                         # damage_taken: only while alive
        fires = _alive_check(w, trig.target + sfx, listener, fires, sfx, read)
    settings = w.obj("oCGameEventListenerSettings", struct.pack("<I", trig.event)
                     + w.obj("oCCustomFlagFilter", w.flags(list(trig.include))
                             + w.flags(list(trig.exclude))) + trig.tail)
    w.add(_LISTENER, listener, {"listener": settings, **{
        s: (fires if s in trig.slots else _NONE) for s in ("ref_3", "ref_4", "ref_5")}},
        flags=trig.flags, group=trig.group if group is None else group)
    return listener


#: The Timer class version whose Serialize writes the trailing picker (corpus:
#: 378 timers at 1.9 all have it, 696 at 1.8 none).
_TIMER_TAIL_AT = (1, 9)


def _timer_tail(w: P.PartWriter) -> dict:
    """The picker Update 6's Timer appends, when this file's Timer class has it
    (``entity_fields.TAIL``)."""
    c = w.ef.cf.classes[w.ci(_TIMER)]
    return {"ref_tail?": _NONE} if (c.version_major, c.version_minor) >= _TIMER_TAIL_AT else {}


def _alive_check(w: P.PartWriter, name: str, listener: str, then: P.Link, sfx: str,
                 read) -> P.Link:
    """damage_taken's gate, as Increase_Shield's: switch ``then`` on only when the
    listener fired and the hero's health ratio is above 0."""
    raw = read(_HEALTH[0])
    if raw is None:
        raise ItemEffectError("effect: the hero's health ratio is not readable "
                              "(no install or mirror)")
    health = EntityFile(raw, "Character_Common").component(_HEALTH[1])
    get = "Entity Get Ration Health Hero Value" + sfx      # sic
    template = w.obj("oCResourceWeakRef", b"".join(P._lstr(x) for x in _HERO))
    method = w.obj("EntityCpntMethodPicker", P.link_bytes(_NONE, w.ci) + b"\xff" * 4)
    got = w.add(_GET, get, {
        "source": w.ids("oCEntityCollectorSelectorSettings", [_owner(w, 0)]),
        "template": template,
        "value": P.Link(health.guid, "[Value] Character_Common\\" + _HEALTH[1]),
        "method": method}, flags=0x101)
    tests = [_float_test(w, got, _GOT_VALUE),
             _float_test(w, w.link(listener, _LISTENER), _LISTENER_FIRED)]
    return _tester(w, name, tests, every=True, flags=0x10001, on_true=then)


def describe(effects: list[Effect], *, one_line: bool = False) -> str:
    """Card text for ``effects``, numbered as `apply_effects` lays out the card:
    "#+{0}%@ #Crit chance@" for an always-on bonus, "During the day, #+{0}%@
    #Crit chance@" for a day/night one, and "After dashing, gain #+{1}%@ #Attack
    power@ for #{2}@ seconds" for a timed one. One bullet each, as the shipped
    cards write several effects; ``one_line`` joins them with ", " instead, as
    super text must be: no shipped super text has a bullet or a line break,
    and the card printed a bulleted one as "???" (playtest 2026-10-24)."""
    lines, n = [], 0
    for e in effects:
        # Attack power entered in points (10) still reads as a percent.
        pct = e.percent or _is_attack_power(e.stat)
        # A negative amount prints its own "-" (shipped curses: "-25%").
        sign = "" if e.amount < 0 else "+"
        amount = f"#{sign}{{{n}}}{'%' if pct else ''}@ #{e.stat}@"
        if e.timed:
            head = (f"{DURING[e.during][1]}, {TRIGGERS[e.on].text.lower()}"
                    if e.during else TRIGGERS[e.on].text)
            lines.append(f"{head}, gain {amount} for #{{{n + 1}}}@ seconds")
            n += 2
        elif e.during:
            lines.append(f"{DURING[e.during][1]}, {amount}")
            n += 1
        else:
            lines.append(amount)
            n += 1
    if one_line:
        return ", ".join(line if not i else line[0].lower() + line[1:]
                         for i, line in enumerate(lines))
    return "\n".join("• " + line for line in lines)


def trigger_texts() -> dict[str, str]:
    """``{on: card wording}`` for the editor's trigger picker."""
    return {k: t.text for k, t in TRIGGERS.items()}


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
    _disarm_cooldown(ef)


_ITEM_DATA = "Dt Magical Object Data"


def _disarm_cooldown(ef: EntityFile) -> None:
    """Give the item data no cooldown. The item is in cooldown while ``value_4``
    (the full time) > 0 and ``value_5 / value_4 < 1``, and in cooldown the icon
    draws a clock and its listeners stay deaf, so ``value_4 = 0`` is what
    disarms it and must hold. ``value_5`` is zeroed when it is a plain number;
    a donor that links it to a timer (Increase_Shield) keeps the link, which
    reads nothing once ``value_4`` is 0."""
    if not any(c.name == _ITEM_DATA for c in ef.graph().components):
        return
    ef.set_value(_ITEM_DATA, "value_4", 0.0)
    try:
        ef.set_value(_ITEM_DATA, "value_5", 0.0)
    except EntityEditError:
        pass


def _card_slots(ef: EntityFile, slots: list[tuple[str, bool]]) -> None:
    """Make the description's ``{0}``, ``{1}``... the given Values, in order: the
    new slots are added after the base's own, which are then dropped."""
    c = ef.component(_DESCRIPTION)
    old = len(ef._format_slots(c)[0])
    for value, percent in slots:
        ef.add_format_slot(_DESCRIPTION, value, percent=percent)
    if not old:
        return
    c = ef.component(_DESCRIPTION)
    found, count_f = ef._format_slots(c)
    at = len(ef.objects[c.index - 1]) - len(c.body)
    p = ef.objects[c.index - 1]
    del p[at + found[0].offset:at + found[old - 1].offset + found[old - 1].size]
    struct.pack_into("<I", p, at + count_f.offset, len(found) - old)
