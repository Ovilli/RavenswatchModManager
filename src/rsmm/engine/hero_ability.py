"""A hero's ability written from data (roadmap "Hero from scratch B").

A button is the shared base's ability-controller slot (``Primary Ability
Controller`` ...) pointed at a state of the hero's own, with its cooldown and
card text: that is the whole difference between the base's empty slot and a
shipped hero's (Geppetto's power: ``ref_2`` -> ``State Primary Ability``,
``value_4`` = 3 s, its name and description).

Behind the state, every part is written here, and the only parts used as a
layout are the shared base's own (``Hero_Common``), never a hero's:

* the ability state (factory) aims the hero (Hero_Common's snap-to-cursor ``Look At``),
  plays its clip (the base dash's clip selector -> clip -> animatic, the
  animatic filled with this ability's clip and length), and starts its timers;
* each hit is a timer (factory) whose end switches on a hit event: the base's
  critical-health explosion (event -> zone attack -> damage, radius value,
  traverser, effect), its radius and damage set from the data;
* an end timer switches the ability state off after the clip, so a button can
  never leave the hero stuck in it.

What it does not do yet: projectiles, movement (leaps, dashes), heals, combo
chains for the basic attack (one swing per press), sounds.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import entity_fields as EF
from . import entity_parts as P
from . import hero_frame as HF
from . import talent_writer as TW
from .entity_graph_edit import EntityEditError, EntityFile

#: Kit slot -> the shared base's controller slot.
CONTROLLERS = {
    "attack": "Basic Attack Controller",
    "power": "Primary Ability Controller",
    "special": "Secondary Ability Controller",
    "defense": "Defensive Ability Controller",
    "trait": "Trait Ability Controller",
    "ultimate": "Ultimate Power 1 Controller",
    "ultimate2": "Ultimate Power 2 Controller",
}
_CLIP = ("Dash Ability Clip Selector", "Dash Ability Clip", "Dash Ability Anim")
#: Hero_Common's tester every shipped ability state activates on entry (see
#: ``build``): it takes the body off the move/idle animation for the ability.
MOVE_INERTIA = "Move Inertia Activation Tester"
#: A button animation's root motion, as shipped attacks read it: Hero_Common's
#: selector, 1 (the clip's full travel) until the target is in range.
ROOT_MOTION_SELECTOR = "Ability In Range Root Motion Value Selector"
OWN_ROOT_MOTION = "Ability Root Motion Selector"
#: What that selector's "in range" reads: Hero_Common's detector, which only
#: looks while a state holds it on. Every shipped attack state holds it
#: (Geppetto's basic attack, Scarlet's wolf attack); a state that did not
#: (Blood Wolf 0.2's power) never saw an enemy in range, and its lunge ran its
#: whole length every time (playtest 2026-11-14).
IN_RANGE_DETECTOR = "Ability In Range Default Detector"
#: The detector's verdict as a tester: copied (as a trigger, not the base's
#: read-only condition) to start a rush's strike.
IN_RANGE_CONDITION = "Ability In Range Default Condition"
#: Character_Common's state that lets attacks pass through (``intangible``).
INTANGIBLE = "State Intangible"
#: `moving`: Hero_Common's state that turns the upper/lower body split on
#: (the hero's "Move Split Layer" blends the ability over its walk), and the
#: controller's two switches that stop movement while the ability runs (off
#: on Blood Wolf 0.1's special, which was cast on the move in game).
SPLIT_ENABLE = "State Anim Split Enable"
MOVING_SWITCHES = ("value_9", "value_10")
#: TEMPORARY bisection variants (see Ability.variant).
_VARIANTS = {"no_end_state", "no_inertia", "bare", "look_enter", "dash_state", "released"}
#: How a button turns the hero: Hero_Common's own dash "Initial Look At To
#: Cursor", which reads the aim accessor (0xfd283d3 on the shared Hero
#: Controller, the one every shipped aimed ability reads) and SNAPS to it
#: (value_6). The dash's plain "Look At" turns to the MOVE direction (shots went
#: where he walked, playtest 2026-11-07); Kintaro's Secondary look-at, used
#: next, turns at 2 pi rad/s, so a shot fired 0.3 s into a wide turn left
#: before he faced the cursor. No hero's part is copied.
LOOK_AT = "Dash Ability Initial Look At To Cursor"
_HIT = ("Event Critical Health Explosion", "Critical Health Explosion Attack",
        "Critical Health Explosion Damage", "Critical Health Explosion Radius",
        "Critical Health Explosion Traverser", "Critical Health Explosion Fx")
_TIMER = "oCEntityCpntTimerSettings"
_NONE = P.Link()


class AbilityError(ValueError):
    pass


#: What a hit can do besides damage: fields of its damage record
#: (``oCDtEntityCpntDamageSettings``; one layout across all 479 shipped records,
#: meanings read off the shipped records that set them: Romeo's cone links its
#: pushback field to "Pushback Value Selector", stuns link "Stun Duration
#: Selector", explosions "Explosion Stagger Value").
#: The ability a damage record counts as (its ``value_35``): what every
#: per-ability stat keys on ("Crit chance basic", "Attack power secondary",
#: "Increase trait damage for each debuff" ...). Read off the shipped hero
#: records by group: Basic 0, Primary 1, Secondary 2, Defensive 3, Trait 4,
#: Ultimate 5, Dash 6; -1 (the donor explosion's) counts as none, so no talent
#: of an ability would touch the hit.
DAMAGE_TYPE = {"attack": 0, "power": 1, "special": 2, "defense": 3, "trait": 4,
               "ultimate": 5, "ultimate2": 5, "dash": 6}
_TYPE_FIELD = "value_35"

#: An ATTACK slot's controller switches, as both shipped state-driven basic
#: attacks write them (Carmilla's and Melusine's "Basic Attack Controller" ->
#: [State]): value_8 can be interrupted, value_11 has a cooldown, value_14 the
#: basic-attack input (held = repeats; only basic attacks and one trait set it).
#: Hero_Common's empty slot has them the other way round (False, True, False),
#: which left a hero written from scratch unable to attack (playtest 2026-11-07).
#: The other buttons keep the base's, as every shipped hero's do.
ATTACK_SWITCHES = {"value_8": True, "value_11": False, "value_14": True}

HIT_FIELDS = {"stun": ("value_27", 0.0, 10.0),        # seconds the enemy is stunned
              "knockback": ("value_4", 0.0, 200.0),   # pushback strength
              "stagger": ("value_31", 0.0, 100.0)}    # stagger power


@dataclass
class Hit:
    at: float                 # seconds after the button
    radius: float = 3.0       # metres
    damage: float = 100.0     # % of a hit
    stun: float = 0.0         # seconds
    knockback: float = 0.0
    stagger: float = 0.0
    status: str = ""          # talent_status.STATUSES: Chilled, Ignite, Bleed, ...
    fx: str = ""              # the burst's look: any shipped .vfx.ot (default Red's bomb)
    shake: str = "none"       # camera shake: none, light, medium, heavy


#: A range indicator: Kintaro's ultimate target ring (a ground decal, the
#: DecalCube with his "Line Limit" ring material; shown in game by his
#: ultimate's target state). The disc mesh first used (Red's) is a part no
#: state shows, and drew nothing in game (playtest 2026-11-07). The ring's box
#: is scaled through two links (x, z: the diameter) and its ring radius is
#: value_10; its parent link (Kintaro's border mesh) is cleared so it hangs on
#: the hero. Its size number is a copy of Red's plain distance value.
INDICATOR_DONOR = ("Heroes\\Hero_Kintaro\\Hero_Kintaro_FX.entity.ot",
                   "Ultimate Ability 1 Target Border Line Mesh")
INDICATOR_SIZE_DONOR = ("Heroes\\Hero_Red\\Hero_Red.entity.ot",
                        "Secondary Ability Can Hold Indicator Max Distance")
_INDICATOR_KEYS = {"radius", "forward", "color"}


@dataclass
class Ability:
    slot: str                 # attack, power, special, defense, trait, ultimate(2)
    clip: str                 # the animation it plays
    cooldown: float = 1.0
    duration: float | None = None   # default: the clip's length
    hits: list[Hit] = field(default_factory=list)
    indicator: dict | None = None    # {radius, forward, color}: a range disc
    bank: str = ""
    name_key: str = ""
    desc_key: str = ""
    sound: str = ""                  # "<entity ref> | <FMod event part>": played at 0 s
    #: Its HUD picture and the greyed one shown while it cools down, each
    #: (root, path) of a cooked UI texture; empty = the button shows none.
    icon: tuple[str, str] = ("", "")
    icon_disabled: tuple[str, str] = ("", "")
    #: TEMPORARY playtest bisection (2026-11-08: states died within a frame).
    #: One or more of, joined with "+": "no_end_state" = the end timer does
    #: not switch the state (its clip ends it, as the dash's does),
    #: "no_inertia" = no move-inertia hand-over, "bare" = both, "look_enter" =
    #: the aim turns once on entry (Geppetto's power) instead of every frame
    #: while active; "dash_state" / "released": see _bisect_state. Remove
    #: once the cause is known.
    variant: str = ""

    def has(self, *variants: str) -> bool:
        """Whether this button's bisection variant includes any of these."""
        return bool(set(self.variant.split("+")) & set(variants))
    #: The basic attack as shipped heroes do it: a combo of steps, each its
    #: own clip whose TIMELINE lands the hit (see build_combo / COMBO_STEP_KEYS).
    combo: list = field(default_factory=list)
    #: How much of the clip's root-bone travel moves the hero (0 = in place);
    #: None = Hero_Common's in-range selector, as shipped attacks use: the
    #: clip's full travel, stopping at the target.
    root_motion: float | None = None
    #: The hero may walk while the ability plays (the move split is on and
    #: the button does not stop movement).
    moving: bool = False
    #: Attacks pass through the hero for the whole ability, its strike too
    #: (Character_Common's "State Intangible", as Scarlet's wolf bite holds it).
    intangible: bool = False
    #: A rush that ends in a strike (Scarlet's wolf bite): ``clip`` is the
    #: lunge, stopping at the first enemy in reach; as soon as one is in reach
    #: the strike's own clip plays and ``hits`` land on ITS timeline. A rush
    #: that reaches no one ends with no strike. Keys: STRIKE_KEYS.
    strike: dict | None = None
    #: A shipped hero's button lent whole (``ability_template``): its own
    #: state machine, effects and timings; ``clip``, ``hits``, ``strike`` ...
    #: are then not this button's to say (its clips and numbers are the
    #: template's ``clips`` / ``values``).
    template: object | None = None

    @classmethod
    def parse(cls, slot: str, raw: dict) -> Ability:
        if slot not in CONTROLLERS:
            raise AbilityError(f"ability {slot!r}: one of {', '.join(CONTROLLERS)}")
        if isinstance(raw, dict) and raw.get("template") is not None:
            return cls._parse_template(slot, raw)
        if isinstance(raw, dict) and raw.get("combo") and not raw.get("clip"):
            raw = {**raw, "clip": (raw["combo"][0] or {}).get("clip", "")}
        if not isinstance(raw, dict) or not raw.get("clip"):
            raise AbilityError(f"ability {slot}: needs clip = <animation>")
        unknown = set(raw) - {"clip", "cooldown", "duration", "hits", "bank", "name_key",
                              "desc_key", "indicator", "sound", "variant", "combo",
                              "icon", "icon_disabled", "root_motion", "moving",
                              "intangible", "strike"}
        if unknown:
            raise AbilityError(f"ability {slot}: no {', '.join(sorted(unknown))}")
        bad = {v for v in str(raw.get("variant", "")).split("+") if v} - _VARIANTS
        if bad:
            raise AbilityError(f"ability {slot}: variant {', '.join(sorted(bad))}; "
                               f"known: {', '.join(sorted(_VARIANTS))} (join with +)")
        hits = parse_hits(raw.get("hits"), f"ability {slot}")
        ind = raw.get("indicator")
        if ind is not None:
            if not isinstance(ind, dict) or set(ind) - _INDICATOR_KEYS \
                    or not 0.2 <= float(ind.get("radius", 3.0)) <= 30 \
                    or not -30 <= float(ind.get("forward", 0.0)) <= 30:
                raise AbilityError(f"ability {slot}: indicator is {{ radius (0.2..30 m), "
                                   "forward (-30..30 m), color = [r, g, b, a] }")
        sound = str(raw.get("sound", ""))
        if sound and (sound.count("|") != 1
                      or not sound.split("|")[0].strip().endswith(".entity.ot")):
            raise AbilityError(f"ability {slot}: sound is \"<Folder\\Entity.entity.ot> | "
                               "<its FMod event part>\"")
        combo = raw.get("combo") or []
        if combo:
            if slot != "attack":
                raise AbilityError(f"ability {slot}: combo is for the basic attack")
            if not isinstance(combo, list) or not COMBO_STEPS <= len(combo) <= COMBO_MAX \
                    or not all(isinstance(st, dict) for st in combo):
                raise AbilityError(f"ability {slot}: combo is a list of {COMBO_STEPS} to "
                                   f"{COMBO_MAX} steps")
            for n, st in enumerate(combo, 1):
                if set(st) - COMBO_STEP_KEYS or not st.get("clip"):
                    raise AbilityError(f"ability {slot}: combo step {n} is {{ clip, "
                                       f"{', '.join(sorted(COMBO_STEP_KEYS - {'clip'}))} }}")
                if len(_step_hits(st, f"ability {slot} combo step {n}")) != 1:
                    raise AbilityError(f"ability {slot}: combo step {n} lands one hit")
        icons = []
        for k in ("icon", "icon_disabled"):
            v = raw.get(k) or ("", "")
            if not (isinstance(v, (tuple, list)) and len(v) == 2
                    and all(isinstance(x, str) for x in v)):
                raise AbilityError(f"ability {slot}: {k} is (root, path) of a UI texture")
            icons.append((str(v[0]), str(v[1])))
        rm = raw.get("root_motion")
        if rm is not None and (isinstance(rm, bool) or not isinstance(rm, (int, float))
                               or not 0 <= rm <= 5):
            raise AbilityError(f"ability {slot}: root_motion is a factor 0..5 of the clip's "
                               "own travel (0 = in place)")
        if rm is not None and combo:
            raise AbilityError(f"ability {slot}: a combo's steps keep the layout's root motion")
        if raw.get("moving") not in (None, True, False) or (raw.get("moving") and combo):
            raise AbilityError(f"ability {slot}: moving is true or false (not on a combo)")
        if raw.get("intangible") not in (None, True, False):
            raise AbilityError(f"ability {slot}: intangible is true or false")
        strike = raw.get("strike")
        if strike is not None:
            if combo or raw.get("moving"):
                raise AbilityError(f"ability {slot}: a strike ends a rush (not a combo, "
                                   "not moving)")
            if not isinstance(strike, dict) or not strike.get("clip") \
                    or set(strike) - STRIKE_KEYS:
                raise AbilityError(f"ability {slot}: strike is {{ clip, "
                                   f"{', '.join(sorted(STRIKE_KEYS - {'clip'}))} }}")
            for k in ("duration", "after"):
                v = strike.get(k)
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                      or not 0 <= v <= 10):
                    raise AbilityError(f"ability {slot}: strike {k} is 0..10 seconds")
            if not hits:
                raise AbilityError(f"ability {slot}: a strike needs hits (on its own clip)")
        return cls(slot, str(raw["clip"]), float(raw.get("cooldown", 1.0)),
                   float(raw["duration"]) if raw.get("duration") is not None else None,
                   hits, ind, str(raw.get("bank", "")), str(raw.get("name_key", "")),
                   str(raw.get("desc_key", "")), sound, icons[0], icons[1],
                   str(raw.get("variant", "")), [dict(st) for st in combo],
                   float(rm) if rm is not None else None, bool(raw.get("moving")),
                   bool(raw.get("intangible")), dict(strike) if strike else None)


#: What a button lent from a shipped hero (``template``) may say besides its
#: knobs: its card, icons and cooldown (default: the donor button's).
TEMPLATE_KEYS = {"template", "clips", "values", "cooldown", "bank", "name_key", "desc_key",
                 "icon", "icon_disabled"}


def _parse_template(cls, slot: str, raw: dict) -> Ability:
    from . import ability_template as AT
    unknown = set(raw) - TEMPLATE_KEYS
    if unknown:
        raise AbilityError(f"ability {slot}: a template button takes "
                           f"{', '.join(sorted(TEMPLATE_KEYS - {'bank', 'name_key', 'desc_key'}))}"
                           f"; not {', '.join(sorted(unknown))} (tune it with values / clips, "
                           "or frame.edits on its parts)")
    try:
        tpl = AT.Template.parse(raw["template"], raw)
    except AT.TemplateError as e:
        raise AbilityError(f"ability {slot}: {e}") from e
    icons = []
    for k in ("icon", "icon_disabled"):
        v = raw.get(k) or ("", "")
        if not (isinstance(v, (tuple, list)) and len(v) == 2):
            raise AbilityError(f"ability {slot}: {k} is (root, path) of a UI texture")
        icons.append((str(v[0]), str(v[1])))
    cd = raw.get("cooldown")
    if cd is not None and (isinstance(cd, bool) or not isinstance(cd, (int, float)) or cd < 0):
        raise AbilityError(f"ability {slot}: cooldown is a number of seconds")
    return cls(slot, "", float(cd) if cd is not None else -1.0, None, [], None,
               str(raw.get("bank", "")), str(raw.get("name_key", "")),
               str(raw.get("desc_key", "")), "", icons[0], icons[1], template=tpl)


Ability._parse_template = classmethod(_parse_template)


#: A strike: its clip (with the hit and the recovery), its length (default the
#: clip's), and how long into the rush before it may start (``after``; Scarlet's
#: bite window opens 0.25 s into her rush, 0 = an enemy already in reach is
#: struck at once).
STRIKE_KEYS = {"clip", "duration", "after"}


def _timer(w: P.PartWriter, name: str, seconds: float, *, on_end: P.Link = _NONE,
           ends: P.Link = _NONE) -> P.Link:
    c = w.ef.cf.classes[w.ci(_TIMER)]
    tail = {"ref_tail?": _NONE} if (c.version_major, c.version_minor) >= (1, 9) else {}
    return w.add(_TIMER, name, {
        "bias?": P.Num.f32(0), "count": P.Num.int(1), "on_tick": _NONE, "on_end": on_end,
        "state": ends, "paused?": P.Num(P.BOOL, b"\x00"), "duration": P.Num.f32(seconds),
        "flag": 0, **tail}, flags=0x1, group=w.group)


def hits(ef: EntityFile, hero_common: EntityFile, w: P.PartWriter, todo: list[Hit], *,
         tag: str, group: str, seed: str, kind: str | None = None) -> list[str]:
    """Each of ``todo`` as a timer whose end switches on a hit event (the base's
    critical-health explosion, its radius and damage set); the timers' names,
    for whatever starts them (an ability state, a talent's action state)."""
    timers: list[str] = []
    for i, hit in enumerate(todo, 1):
        pre = f"{tag} Hit {i}"
        names = {"Event Critical Health Explosion": f"Event {pre}",
                 "Critical Health Explosion Attack": f"{pre} Attack",
                 "Critical Health Explosion Damage": f"{pre} Damage",
                 "Critical Health Explosion Radius": f"{pre} Radius",
                 "Critical Health Explosion Traverser": f"{pre} Traverser",
                 "Critical Health Explosion Fx": f"{pre} Fx"}
        ef.clone([f"MO Critical Health Explosion\\{n}" for n in _HIT],
                 seed=f"{seed}:hit{i}", rename=names,
                 group={"MO Critical Health Explosion": group}, source=hero_common)
        ef.set_value(f"{pre} Radius", "value", hit.radius)
        ef.set_value(f"{pre} Damage", "value_28", hit.damage / 100.0)
        if kind in DAMAGE_TYPE:
            ef.set_value(f"{pre} Damage", _TYPE_FIELD, DAMAGE_TYPE[kind])
        if hit.fx:
            set_fx(ef, f"{pre} Fx", hit.fx)
        if hit.shake != "medium":
            set_fx(ef, f"{pre} Fx", SHAKES[hit.shake], old=DONOR_SHAKE)
        for key, (fld, _lo, _hi) in HIT_FIELDS.items():
            if getattr(hit, key):
                ef.set_value(f"{pre} Damage", fld, float(getattr(hit, key)))
        _timer(w, f"{pre} Timer", max(hit.at, 0.0), on_end=TW.link_to(ef, f"Event {pre}"))
        timers.append(f"{pre} Timer")
    return timers


_HIT_KEYS = {"at", "radius", "damage", "status", "fx", "shake", *HIT_FIELDS}

#: The donor explosion shakes the camera (Common_FX's medium explosion shake)
#: on EVERY hit; a hit shakes only when asked. "none" points the shake's setup
#: at an effect of nothing the SDK writes (vfx_writer.NO_EFFECT; was Kintaro's
#: empty effect). It stays on the list: an unreferenced setup is a sub-object
#: no later clone can attribute ("cannot tell whether sub-object ... belongs").
#: The others swap in the matching shipped Common_FX shake.
DONOR_SHAKE = "Settings\\FX\\Common_FX\\Camera_Shake_Explosion_Medium.vfx.ot"
NO_FX = "Settings\\FX\\Common_FX\\RSMM_No_Effect.vfx.ot"
SHAKES = {"none": NO_FX,
          "light": "Settings\\FX\\Common_FX\\Camera_Shake_Explosion_Light.vfx.ot",
          "medium": DONOR_SHAKE,
          "heavy": "Settings\\FX\\Common_FX\\Camera_Shake_Explosion_Heavy.vfx.ot"}

#: The donor explosion's own look (Hero_Common's critical-health explosion
#: borrows Red's bomb): what `fx` replaces, in the hit's own copy only.
DONOR_FX = "Settings\\Heroes\\Hero_Red_FX\\RED_Bomb_Explosion_5m.vfx.ot"


def set_fx(ef: EntityFile, fx_part: str, vfx: str, *, old: str = "") -> None:
    """The effect ``fx_part`` plays: its own FX-setup sub-objects (bytes_1,
    u32 count + ids; each hit owns its copies) have the donor's look swapped
    for ``vfx`` (a length-prefixed string, rewritten whole)."""
    import struct

    from . import entity_fields as EF
    c = ef.component(fx_part)
    f = next(x for x in EF.fields(c) if x.name == "bytes_1")
    raw = c.body[f.offset:f.offset + f.size]
    (n,) = struct.unpack_from("<I", raw)
    old_s = old or DONOR_FX
    old, new = old_s.encode("latin-1"), vfx.encode("latin-1")
    done = 0
    for i in struct.unpack_from(f"<{n}I", raw, 4):
        p = ef.objects[i]
        at = bytes(p).find(struct.pack("<I", len(old)) + old)
        if at >= 0:
            p[at:at + 4 + len(old)] = struct.pack("<I", len(new)) + new
            done += 1
    if not done:
        raise AbilityError(f"{fx_part}: no {old_s} to replace")


def parse_hits(raw, what: str) -> list[Hit]:
    from .talent_status import STATUSES
    out = []
    for n, h in enumerate(raw or [], 1):
        if not isinstance(h, dict) or "at" not in h or set(h) - _HIT_KEYS:
            raise AbilityError(f"{what}: hits[{n}] is {{ {', '.join(sorted(_HIT_KEYS))} }}")
        extra = {}
        for key, (_fld, lo, hi) in HIT_FIELDS.items():
            v = float(h.get(key, 0.0))
            if not lo <= v <= hi:
                raise AbilityError(f"{what}: hits[{n}].{key} = {v}: {lo}..{hi}")
            extra[key] = v
        status = str(h.get("status", ""))
        if status and status not in STATUSES:
            raise AbilityError(f"{what}: hits[{n}].status = {status!r}: one of "
                               f"{', '.join(STATUSES)}")
        fx = str(h.get("fx", ""))
        if fx and not fx.endswith(".vfx.ot"):
            raise AbilityError(f"{what}: hits[{n}].fx = {fx!r}: a shipped effect "
                               "(Settings\\...\\<name>.vfx.ot)")
        shake = str(h.get("shake", "none"))
        if shake not in SHAKES:
            raise AbilityError(f"{what}: hits[{n}].shake = {shake!r}: one of {', '.join(SHAKES)}")
        out.append(Hit(float(h["at"]), float(h.get("radius", 3.0)),
                       float(h.get("damage", 100.0)), status=status, fx=fx, shake=shake,
                       **extra))
    return out


def indicator(ef: EntityFile, spec: dict, *, tag: str, group: str, seed: str) -> str:
    """A range ring of the hero's own (``INDICATOR_DONOR``), ``spec`` = {radius,
    forward, color}; returns its name, for a state to show ``while_active``."""
    from . import corpus

    def donor(ref: str) -> EntityFile:
        raw = corpus.read(f"EntitySettings/{ref.replace(chr(92), '/')}.EntitySettingsResource.gen")
        if raw is None:
            raise AbilityError(f"{ref} is not in the game files")
        return EntityFile(raw, ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot"))
    ring_ref, ring = INDICATOR_DONOR
    size_ref, size = INDICATOR_SIZE_DONOR
    rd, sd = donor(ring_ref), donor(size_ref)
    m, v = f"{tag} Indicator", f"{tag} Indicator Size"
    radius = float(spec.get("radius", 3.0))
    ef.clone([ring], rename={ring: m}, source=rd, seed=f"{seed}:indicator",
             group={rd.component(ring).group: group})
    ef.clone([size], rename={size: v}, source=sd, seed=f"{seed}:indicator-size",
             group={sd.component(size).group: group})
    ef.set_value(v, "value", 2.0 * radius)              # the box spans the diameter
    ef.set_ref(m, "obj_3[0]", v)
    ef.set_ref(m, "obj_3[1]", v)
    ef.set_ref(m, "obj_4[0]", None)                     # hang on the hero, not Kintaro's mesh
    ef.set_value(m, "value_10", radius)                 # the ring's own radius
    if spec.get("forward"):
        ef.set_value(m, "obj_4[5]", float(spec["forward"]))
    if spec.get("color"):
        r, g, b, a = [*spec["color"], 1.0][:4]
        ef.set_value(m, "value_7", (float(r), float(g), float(b), float(a)))
    return m


def statuses(ef: EntityFile, todo: list[Hit], *, tag: str, switch: str, seed: str) -> None:
    """Each of ``todo``'s hits with a ``status`` also puts it on whoever it hits
    while ``switch`` (the ability's state, a talent's action state) is on: a copy
    of a shipped debuff of that status on the hit's damage record
    (``talent_status``)."""
    from . import talent_status as TS
    donors: dict[str, tuple] = {}
    for i, hit in enumerate(todo, 1):
        if not hit.status:
            continue
        if hit.status not in donors:
            donors[hit.status] = TS.donor_of(hit.status)
        donor, donor_raw = donors[hit.status]
        try:
            TS.add_status(ef, donor, donor_raw, damage=f"{tag} Hit {i} Damage",
                          status=hit.status, switch=switch, talent=tag,
                          seed=f"{seed}:status{i}")
        except TS.StatusError as e:
            raise AbilityError(f"{tag} hit {i}: {e}") from e


def add_indicator(ef: EntityFile, ab: Ability, *, seed: str) -> None:
    """``ab``'s range disc, shown while its state runs. Added LAST, once every
    other part (kit timelines included) is written: the disc's copied parts
    make the file's sub-object ownership scan ambiguous for any later clone of
    the hero's own parts (a kit step failed on them)."""
    if ab.indicator is None:
        return
    word = ab.slot.title()
    tag = f"{word} Ability"
    disc = indicator(ef, ab.indicator, tag=tag, group=f"Ability {word}",
                     seed=f"{seed}:{ab.slot}")
    ef.add_ref(f"State {tag}", "while_active", disc)


#: Blocs of the dash's timeline that are the DASH's, not an ability's: its
#: whoosh sound at 0 s and its dodge invulnerability (Character_Common's
#: "State Intangible") at 0.35 s. Left in, every button played the dash sound
#: and made the hero intangible (found 2026-11-08).
_DASH_ONLY_BLOCS = (b"\\Ability Dash\\Dash Ability FMod Event", b"\\Base\\State Intangible")
#: When an ability may end: ``ABILITY_EXIT`` fires at this share of its clip
#: (Geppetto's power release: 0.43 s of 0.8 s; the dash's own 0.35 s was cut
#: into every ability, whatever its length).
EXIT_SHARE = 0.75


def own_sound(ef: EntityFile, spec: str, *, name: str, group: str, seed: str) -> str:
    """A shipped sound (``"<entity ref> | <FMod event part>"``, e.g. the Dark
    Hills Jack NPC's ``Beanstalk ShakeImpact FMod Event``) copied into the hero
    as its own part ``name``: an FMod event part holds its bank and event id
    and links nothing, so the copy stands alone. Returns ``name``."""
    from . import corpus
    ref, part = (x.strip() for x in spec.split("|"))
    raw = corpus.read(f"EntitySettings/{ref.replace(chr(92), '/')}.EntitySettingsResource.gen")
    if raw is None:
        raise AbilityError(f"sound: {ref} is not in the game files")
    donor = EntityFile(raw, ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot"))
    try:
        c = donor.component(part)
    except EntityEditError as e:
        raise AbilityError(f"sound: {ref} has no {part!r}") from e
    if c.cls != "oCEntityCpntFModEventSettings":
        raise AbilityError(f"sound: {part!r} is a {c.cls}, not an FMod event")
    ef.clone([c.path], rename={part: name}, group={c.group: group}, seed=seed, source=donor)
    return name


def _repoint_bloc(ef: EntityFile, i: int, target: str) -> None:
    """Bloc object ``i``'s link (an oCEntityCpntPicker: begin mark, class,
    GUID, label, end mark) re-pointed at the part ``target``."""
    import struct
    names = [x.name for x in ef.cf.classes]
    b = ef.objects[i]
    at = bytes(b).find(P._B + struct.pack("<I", names.index("oCEntityCpntPicker")))
    if at < 0:
        raise AbilityError(f"timeline bloc {i}: no link")
    n = struct.unpack_from("<I", b, at + 8 + 16)[0]
    end = at + 8 + 16 + 4 + n + len(P._E)
    b[at:end] = ef._picker(target)


def own_timeline(ef: EntityFile, anim: str, length: float, *, sound: str = "") -> None:
    """``anim``'s timeline (``oCCinematic``: bloc count, bloc object ids,
    length), copied from the dash, made the ability's own: ``ABILITY_EXIT``
    moves to ``EXIT_SHARE`` of ``length``, and each dash-only bloc starts after
    the timeline ends, so it never fires. The blocs stay where they are (no
    object leaves the file: only start times change). A bloc's start time is
    the f32 after its class index."""
    import struct

    names = [x.name for x in ef.cf.classes]
    c = ef.component(anim)
    p = ef.objects[c.index - 1]
    pos = p.find(P._B + struct.pack("<I", names.index("oCCinematic")))
    if pos < 0:
        raise AbilityError(f"{anim}: no timeline")
    count = struct.unpack_from("<I", p, pos + 8)[0]
    for i in struct.unpack_from(f"<{count}I", p, pos + 12):
        bloc = ef.objects[i]
        if sound and _DASH_ONLY_BLOCS[0] in bytes(bloc):
            _repoint_bloc(ef, i, sound)        # its own sound, at the same 0 s
        elif any(m in bytes(bloc) for m in _DASH_ONLY_BLOCS):
            struct.pack_into("<f", bloc, 4, length + 60.0)
        elif b"ABILITY_EXIT" in bytes(bloc):
            struct.pack_into("<f", bloc, 4, max(0.2, EXIT_SHARE * length))


def _bisect_state(ef: EntityFile, hero_common: EntityFile, ab: Ability, *, ctl: str,
                  state: str, tag: str, group: str, timers: list[str], seed: str) -> None:
    """TEMPORARY playtest bisection (2026-11-08): the ability's own state dies
    within a frame while the dash's lives. ``variant = "dash_state"`` points
    the button at Hero_Common's own dash state (does the button side work?);
    ``"released"`` adds the input-released flag + tester every shipped
    ability state has. Remove once the cause is known."""
    if not ab.has("dash_state", "released"):
        return
    if ab.has("dash_state"):
        ds = hero_common.component("State Dash Ability")
        ef.retarget_external(ctl, ef.component(state).guid, ds.guid,
                             f"[State] {hero_common.name}\\{ds.path}")
        return
    # "released": the input-released flag + tester both shipped states have
    # (the dash's and Geppetto's power): reset on entry, set on button-up.
    names = ("Dash Ability Input Has Been Released Flag",
             "Dash Ability Input Has Been Released Tester")
    ef.clone([hero_common.component(n).path for n in names],
             rename={n: n.replace("Dash Ability", tag) for n in names},
             group={"Ability Dash": group}, seed=f"{seed}:{ab.slot}:released",
             source=hero_common)
    flag, tester = (n.replace("Dash Ability", tag) for n in names)
    ef.set_ref(tester, "ref_6", None)          # the dash's active timer: not ours
    ef.add_ref(state, "deactivates?", flag)
    ef.add_ref(state, "while_active", tester)


#: The basic attack's combo layout. The shared base has none (an attack combo
#: exists only inside heroes), so one shipped hero lends the LAYOUT only, as
#: Aladdin's sword lends the hand-weapon slot: every link and every asset is
#: re-pointed at the hero's own parts (build_combo). Geppetto's is two steps:
#: combo -> step states -> clip selectors -> clips -> animatics, each step's
#: timeline landing its hit ("Event ... Active Step N"), COMBO_LINK (when the
#: next press chains) and ABILITY_EXIT (when he may move again).
COMBO_DONOR = ("Heroes\\Hero_Geppetto\\Hero_Geppetto.entity.ot", "Hero_Geppetto", "Basic Ability")
COMBO_STEPS = 2
#: Longer combos: each further step is a copy of the layout's LAST step (its
#: state, clip selector, clip and animatic) and of the combo's last entry,
#: re-pointed at that copy. A combo's entries are a plain list (``bytes_4``:
#: count + entry ids, each entry naming its step state), and a third entry
#: added this way ran in game on a clone of Scarlet's wolf (Blood Wolf 0.1).
COMBO_MAX = 4
#: How long a combo step must keep playing after its exit for the next press
#: to chain (shipped steps keep 1-3 s; the shortest tail is Geppetto's step 2,
#: 1.07 s).
COMBO_TAIL = 0.5
_COMBO_STEP_PARTS = ("State {p} Step {n}", "{p} Clip Selector Step {n}",
                     "{p} Clip Step {n}", "{p} Anim Step {n}")
_COMBO_PARTS = ("{p} Combo Selector", "{p} Combo", "State {p} Step {n}",
                "{p} Clip Selector Step {n}",
                "{p} Clip Step {n}", "{p} Anim Step {n}")
#: A combo step: its clip, when its hit lands, when the next press chains
#: (COMBO_LINK) and when he may move (ABILITY_EXIT), seconds into the clip;
#: its voice/swing sound at 0 s and its weapon whoosh at ``swing_at``.
COMBO_STEP_KEYS = {"clip", "duration", "hit_at", "link_at", "exit_at", "sound", "swing",
                   "swing_at", "hits"}


def _step_hits(st: dict, what: str) -> list:
    """A combo step's hits: its timeline lands them, at the step's ``hit_at``."""
    todo = [{"at": st.get("hit_at", 0.0), **h} if isinstance(h, dict) else h
            for h in (st.get("hits") or [])]
    return parse_hits(todo, what)


def _combo_controller_by_base_guid(ef: EntityFile, hero_common: EntityFile, combo: str,
                                   ctl: str) -> None:
    """Point the combo's controller link at the SHARED BASE's slot GUID.

    The hero's controller is an override of Hero_Common's slot, and at run
    time the button is known by the base slot's GUID: 17 of 17 shipped combos
    on a main slot (Geppetto's, Scarlet's wolf, Kintaro's ...) link that GUID
    under their own file's label, never their override's own GUID. Linked by
    the override's own GUID, the combo never matched its button: every press
    started it again at step 1 (Blood Wolf 0.2 playtest 2026-11-14: "it just
    repeats a single claw swipe")."""
    own = ef.component(ctl).guid
    base = hero_common.component(ctl).guid
    label = next((r.path for r in ef.component(combo).refs if r.guid == own), None)
    if label is None:
        raise AbilityError(f"the combo does not link its controller {ctl!r}")
    if not ef.retarget_external(combo, own, base, label):
        raise AbilityError(f"the combo's link to {ctl!r} could not be re-pointed")


def build_combo(ef: EntityFile, hero_common: EntityFile, ab: Ability, *, seed: str,
                tag: str, group: str) -> str:
    """The basic attack as a combo (see ``COMBO_DONOR``). Returns its state.

    The button enters the hero's attack state, which starts the combo on
    entry; the combo runs its step states, each playing its own clip. Each
    step's timeline is rewritten as the hero's: the donor's swing sound and
    speed lines become the hero's sound parts, its hit event the hero's own
    hit (``hits``, an area hit with its effect and shake), COMBO_LINK and
    ABILITY_EXIT move to the step's times, and the donor's footsteps never
    fire. Nothing links into the donor once built."""
    import struct

    from . import corpus
    ref, name, pre = COMBO_DONOR
    raw = corpus.read(f"EntitySettings/{ref.replace(chr(92), '/')}.EntitySettingsResource.gen")
    if raw is None:
        raise AbilityError("the combo layout's hero is not in the game files")
    donor = EntityFile(raw, name)
    parts = [p.format(p=pre, n=n) for p in _COMBO_PARTS for n in range(1, COMBO_STEPS + 1)]
    parts = list(dict.fromkeys(parts))
    ctl = CONTROLLERS[ab.slot]
    HF.fill_slot(ef, hero_common, ctl, seed=seed)     # before the copy links to it
    ef.clone([donor.component(p).path for p in parts],
             rename={p: p.replace(pre, tag) for p in parts},
             group={donor.component(parts[0]).group: group},
             seed=f"{seed}:{ab.slot}:combo", source=donor)
    combo = f"{tag} Combo"
    # Steps past the layout's: copied from its last step BEFORE that step's
    # timeline is rewritten below, so each copy is rewritten as its own.
    last = COMBO_STEPS
    for n in range(COMBO_STEPS + 1, len(ab.combo) + 1):
        src = [p.format(p=tag, n=last) for p in _COMBO_STEP_PARTS]
        ef.clone([ef.component(p).path for p in src],
                 rename={p: p.replace(f"Step {last}", f"Step {n}") for p in src},
                 seed=f"{seed}:{ab.slot}:combo-step{n}")
        c = ef.component(combo)
        f = next(x for x in EF.fields(c) if x.name == "bytes_4")
        count = struct.unpack_from("<I", c.body, f.offset)[0]
        entry = struct.unpack_from("<I", c.body, f.offset + 4 * count)[0]    # the last one
        ef.add_subobject(combo, "bytes_4", ef, entry, refs={
            ef.component(f"State {tag} Step {last}").guid: f"State {tag} Step {n}"})
        parts += [p.format(p=pre, n=n) for p in _COMBO_STEP_PARTS]
    w = TW.TalentWriter(ef, f"{seed}:{ab.slot}", group)
    state = f"State {tag}"
    w.state(state, flags=TW.PERSISTENT)
    # its parent state and controller: the hero's (by the GUID the copied link
    # holds -- a controller link names the shared base's slot, not the donor's)
    mine = {f"State {pre}": state, "Basic Attack Controller": ctl}
    for r in ef.component(combo).refs:
        target = mine.get(r.path.rsplit("\\", 1)[-1])
        if target and r.path.split("] ", 1)[-1].startswith(donor.name + "\\"):
            ef.swap_refs(combo, r.guid, target)
    _combo_controller_by_base_guid(ef, hero_common, combo, ctl)
    # The button and the state go through the combo SELECTOR, as the donor's
    # do: the combo switches its parent state on, so a state that started the
    # combo itself re-entered forever and hung the game on the first press
    # (playtest 2026-11-08). The selector's first entry is a talent finisher's
    # combo, picked while that talent's state is on: here the hero's own combo
    # behind a state of its own that nothing switches on, so the default
    # (its combo) is always the one picked.
    sel = f"{tag} Combo Selector"
    never = f"State {tag} Finisher Off"
    w.state(never, flags=TW.PERSISTENT)
    for r in ef.component(sel).refs:
        if r.path.split("] ", 1)[-1].startswith(donor.name + "\\"):
            ef.swap_refs(sel, r.guid, combo if r.path.startswith("[Dt Attack Combo]") else never)
    ef.add_ref(state, "on_enter?", sel)
    mi = hero_common.component(MOVE_INERTIA)
    ef.add_external_ref(state, "activates", mi.guid,
                        f"[{HF.kind_label(mi.cls)}] {hero_common.name}\\{mi.path}")
    # The steps' root motion reads the in-range selector: the detector it
    # reads looks only while held (both shipped combo parents hold it).
    _hold_in_range(ef, hero_common, state)
    ef.set_ref(ctl, "ref_2", sel)
    names = [x.name for x in ef.cf.classes]
    for n, st in enumerate(ab.combo, 1):
        clip = str(st["clip"])
        length = float(st.get("duration") or HF.clip_length(clip) or 0)
        if not length:
            raise AbilityError(f"combo step {n}: the game has no clip {clip!r}")
        anim = f"{tag} Anim Step {n}"
        import re
        old = re.search(rb"Characters\\[ -~]*?\.fbx", ef.component(anim).body)
        if old is None:
            raise AbilityError(f"combo step {n}: the layout's animatic names no clip")
        HF.replace_in_slot(ef, anim, old.group(0).decode(), clip)
        HF._set_duration(ef, anim, length)
        step_hits = _step_hits(st, f"combo step {n}")
        hits(ef, hero_common, w, step_hits, tag=f"{tag} Step {n}", group=group,
             seed=f"{seed}:{ab.slot}:step{n}", kind=ab.slot)
        hit_event = f"Event {tag} Step {n} Hit 1"
        snd = (own_sound(ef, st["sound"], name=f"{tag} Sound Step {n}", group=group,
                         seed=f"{seed}:{ab.slot}:sound{n}") if st.get("sound") else "")
        swing = (own_sound(ef, st["swing"], name=f"{tag} Swing Sound Step {n}", group=group,
                           seed=f"{seed}:{ab.slot}:swing{n}") if st.get("swing") else "")
        hit_at = float(st.get("hit_at", 0.35 * length))
        times = {"COMBO_LINK": float(st.get("link_at", hit_at + 0.1)),
                 "ABILITY_EXIT": float(st.get("exit_at", hit_at + 0.2))}
        if n < len(ab.combo) and length < times["ABILITY_EXIT"] + COMBO_TAIL:
            # The next press chains only while this step still plays: shipped
            # steps keep their whole clip (Scarlet's wolf claw: exit 0.62 s of
            # 3.82 s). Cut at 0.55 s, Blood Wolf's first claw ended before the
            # press was taken and the combo restarted every time.
            raise AbilityError(
                f"combo step {n}: it ends at {length:.2f} s, too soon after its exit "
                f"({times['ABILITY_EXIT']:.2f} s) for the next press to chain; leave "
                f"`duration` out (the whole clip) or make it at least "
                f"{times['ABILITY_EXIT'] + COMBO_TAIL:.2f} s")
        c = ef.component(anim)
        p = ef.objects[c.index - 1]
        pos = p.find(P._B + struct.pack("<I", names.index("oCCinematic")))
        count = struct.unpack_from("<I", p, pos + 8)[0]
        for i in struct.unpack_from(f"<{count}I", p, pos + 12):
            bloc = bytes(ef.objects[i])
            if b"Default Attack Look At" in bloc:
                continue                                    # Hero_Common's: shared
            event = next((e for e in times if e.encode() in bloc), None)
            if event:
                struct.pack_into("<f", ef.objects[i], 4, times[event])
            elif b"Active Step" in bloc:                    # the donor's hit
                _repoint_bloc(ef, i, hit_event)
                struct.pack_into("<f", ef.objects[i], 4, hit_at)
            elif b"FMod Event Anim Step" in bloc and snd:   # its voice / swing at 0 s
                _repoint_bloc(ef, i, snd)
            elif b"Speed Lines Fx" in bloc and swing:       # the whoosh
                _repoint_bloc(ef, i, swing)
                struct.pack_into("<f", ef.objects[i], 4, float(st.get("swing_at", hit_at - 0.1)))
            else:                                           # footsteps, unused donor parts
                struct.pack_into("<f", ef.objects[i], 4, length + 60.0)
                if donor.name.encode() in bloc:
                    _repoint_bloc(ef, i, state)             # nothing links into the donor
    # Per step: a step's hits are its own parts ("<tag> Step <n> Hit <i>"), so
    # a status is put on that step's damage record. (One call over every hit
    # looked for "<tag> Combo Hit <i>", which no step builds: a combo hit with
    # a status stopped the build.)
    for n, st in enumerate(ab.combo, 1):
        statuses(ef, _step_hits(st, f"combo step {n}"), tag=f"{tag} Step {n}", switch=state,
                 seed=f"{seed}:{ab.slot}:step{n}")
    left = [r.path for p in parts for r in ef.component(p.replace(pre, tag)).refs
            if r.path.split("] ", 1)[-1].startswith(donor.name + "\\")]
    if left:
        raise AbilityError(f"the combo still links its layout's hero: {left[:3]}")
    return state


def _button(ef: EntityFile, ab: Ability, ctl: str) -> None:
    """The button's own settings: cooldown, the basic attack's switches, card text."""
    # The manifest's cooldown, the basic attack's too: a combo is also paced by
    # its timeline (COMBO_LINK / ABILITY_EXIT); a single-state attack has no
    # other pacing, and at 0 it could be spammed every frame (playtest
    # 2026-11-08). Shipped basic attacks use 0 or 1.
    if ab.cooldown >= 0:                  # a template keeps its donor's (-1)
        ef.set_value(ctl, "value_4", float(ab.cooldown))
    if ab.slot == "attack" and ab.template is None:
        for fld, on in ATTACK_SWITCHES.items():
            ef.set_value(ctl, fld, on)
    if ab.desc_key:
        HF._set_text(ef, ctl, ab.bank, ab.desc_key)
    if ab.name_key:
        HF._set_text(ef, ctl, ab.bank, ab.name_key)
    if ab.icon[1]:
        set_icon(ef, ctl, ab.icon, ab.icon_disabled if ab.icon_disabled[1] else ab.icon)


#: The HUD picture of a button lives in an object its controller owns
#: (bytes_13 = u32 1, u32 n, n object ids: one per step, Juliet's 4-hit attack
#: has 4). Its body ends with two (root, path) string pairs, the picture and
#: its cooled-down twin, after this marker; Hero_Common leaves both empty.
ICON_CLASS = "oCDtAbilityAlternateIconSettings"
_ICON_MARK = bytes.fromhex("2222bbaa2222bbaa")


def icons_of(ef: EntityFile, ctl: str) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """The HUD pictures button ``ctl`` holds, one (picture, cooled-down) pair
    per step it owns (see :data:`ICON_CLASS`); empty pairs left out."""
    from . import entity_fields as EF
    c = ef.component(ctl)
    f = next((x for x in EF.fields(c) if x.name == "bytes_13"), None)
    raw = bytes(c.body[f.offset:f.offset + f.size]) if f is not None else b""
    if len(raw) < 8:
        return []
    n = struct.unpack_from("<I", raw, 4)[0]
    if len(raw) != 8 + 4 * n:
        return []
    out = []
    for i in struct.unpack_from(f"<{n}I", raw, 8):
        if ef._class(i) != ICON_CLASS:
            continue
        obj = bytes(ef.objects[i])
        at = obj.find(_ICON_MARK)
        if at < 0:
            continue
        pos, strs = at + len(_ICON_MARK), []
        while pos + 4 <= len(obj) and len(strs) < 4:
            (ln,) = struct.unpack_from("<I", obj, pos)
            strs.append(obj[pos + 4:pos + 4 + ln].decode("latin-1"))
            pos += 4 + ln
        if len(strs) == 4 and strs[1]:
            out.append(((strs[0], strs[1]), (strs[2], strs[3] or strs[1])))
    return out


def set_icon(ef: EntityFile, ctl: str, icon: tuple[str, str],
             disabled: tuple[str, str]) -> int:
    """Give the button ``ctl`` its HUD pictures, on every step it owns; how many."""
    from . import entity_fields as EF
    c = ef.component(ctl)
    f = next((x for x in EF.fields(c) if x.name == "bytes_13"), None)
    raw = bytes(c.body[f.offset:f.offset + f.size]) if f is not None else b""
    if len(raw) < 8:
        raise AbilityError(f"{ctl}: no icon list")
    n = struct.unpack_from("<I", raw, 4)[0]
    if len(raw) != 8 + 4 * n or not n:
        raise AbilityError(f"{ctl}: icon list of {len(raw)} bytes for {n} steps")
    ids = struct.unpack_from(f"<{n}I", raw, 8)
    for i in ids:
        if ef._class(i) != ICON_CLASS:
            raise AbilityError(f"{ctl}: object {i} is {ef._class(i)}, not {ICON_CLASS}")
        obj = ef.objects[i]
        at = bytes(obj).find(_ICON_MARK)
        if at < 0 or bytes(obj).count(_ICON_MARK) != 1:
            raise AbilityError(f"{ctl}: icon object {i} has no picture slots")
        obj[at + len(_ICON_MARK):] = (P._lstr(icon[0]) + P._lstr(icon[1])
                                      + P._lstr(disabled[0]) + P._lstr(disabled[1]))
    return len(ids)


def _hold_external(ef: EntityFile, base: EntityFile, state: str, part: str,
                   field: str = "while_active") -> None:
    """Link the base's part ``part`` (one the hero inherits) into ``state``."""
    c = base.component(part)
    ef.add_external_ref(state, field, c.guid, f"[{HF.kind_label(c.cls)}] {base.name}\\{c.path}")


def _hold_in_range(ef: EntityFile, hero_common: EntityFile, state: str) -> None:
    _hold_external(ef, hero_common, state, IN_RANGE_DETECTOR)


def _hold_intangible(state: str, ef: EntityFile) -> None:
    from .talent_add_stat import _common_state
    link = _common_state(INTANGIBLE)
    ef.add_external_ref(state, "while_active", link.guid, link.path)


def _build_strike(ef: EntityFile, hero_common: EntityFile, w: TW.TalentWriter, ab: Ability, *,
                  tag: str, group: str, state: str, hit_timers: list[str],
                  seed: str) -> tuple[P.Link, str]:
    """The strike that ends a rush (``Ability.strike``), as Scarlet's wolf bite:

    * ``State <tag> Strike`` plays the strike's clip, aims, holds the in-range
      detector (its root motion stops at the enemy too), lands the ability's
      hits on its own timeline and ends itself after the clip;
    * ``Event <tag> Strike`` switches the rush (``state``) off and the strike on;
    * ``<tag> Strike Tester`` (a copy of Hero_Common's in-range condition, made a
      trigger) fires that event while ``State <tag> Strike Window`` is on: the
      window opens ``after`` seconds into the rush (Scarlet's: 0.25 s, from her
      rush's timeline), so an enemy already in reach is struck at once;
    * ``Event <tag> Rush End`` closes the rush and its window when the lunge
      ran out with no one in reach: no strike (a window left on would strike
      later, out of nowhere).

    Returns the rush-end event (for the rush's end timer) and the window's
    timer (for the rush state to start)."""
    st = ab.strike or {}
    stag = f"{tag} Strike"
    clip = str(st["clip"])
    length = float(st.get("duration") or HF.clip_length(clip) or 0)
    if not length:
        raise AbilityError(f"ability {ab.slot}: the game has no strike clip {clip!r}")
    ef.clone([f"Ability Dash\\{n}" for n in _CLIP], seed=f"{seed}:{ab.slot}:strike-clip",
             rename={n: n.replace("Dash Ability", stag) for n in _CLIP},
             group={"Ability Dash": group}, source=hero_common)
    HF._set_clips(ef, f"{stag} Anim", [clip])
    HF._set_duration(ef, f"{stag} Anim", length)
    ef.set_value(f"{stag} Anim", HF.ROOT_MOTION, 1.0)
    ef.set_ref(f"{stag} Anim", HF.ROOT_MOTION, OWN_ROOT_MOTION)
    own_timeline(ef, f"{stag} Anim", length)
    strike = f"State {stag}"
    strike_link = w.state(strike, while_active=[TW.link_to(ef, f"{stag} Clip Selector"),
                                                TW.link_to(ef, f"{tag} Look At")],
                          flags=TW.PERSISTENT)
    _timer(w, f"{stag} End Timer", length, ends=strike_link)
    for t in [*hit_timers, f"{stag} End Timer"]:
        ef.add_ref(strike, "activates", t)
    _hold_external(ef, hero_common, strike, MOVE_INERTIA, "activates")
    _hold_in_range(ef, hero_common, strike)
    if ab.intangible:
        _hold_intangible(strike, ef)
    ef.set_ref(f"{stag} Clip", "ref_11", strike)
    window = f"State {stag} Window"
    window_link = w.state(window, flags=TW.PERSISTENT)
    w.state(f"Event {stag}", activates=[strike_link],
            deactivates=[TW.link_to(ef, state), window_link], flags=TW.EVENT)
    cond = hero_common.component(IN_RANGE_CONDITION)
    tester = f"{stag} Tester"
    ef.clone([cond.path], rename={IN_RANGE_CONDITION: tester}, group={cond.group: group},
             seed=f"{seed}:{ab.slot}:strike-tester", source=hero_common)
    ef.set_flags(tester, TW.PERSISTENT)        # a trigger, as Scarlet's bite tester
    ef.set_ref(tester, "on_true", f"Event {stag}")
    ef.add_ref(window, "while_active", tester)
    _timer(w, f"{stag} Window Timer", float(st.get("after", 0.25)), on_end=window_link)
    rush_end = w.state(f"Event {tag} Rush End",
                       deactivates=[TW.link_to(ef, state), window_link], flags=TW.EVENT)
    return rush_end, f"{stag} Window Timer"


def _corpus_read(ref: str):
    from . import corpus
    return corpus.read("EntitySettings/" + ref.replace("\\", "/") + ".EntitySettingsResource.gen")


def build_template(ef: EntityFile, hero_common: EntityFile, ab: Ability, *, seed: str,
                   read=None) -> str:
    """``ab``'s button lent from a shipped hero (``ability_template.lend``):
    the hero's controller slot filled and pointed at the copy's entry, with
    the donor's switches, and the manifest's cooldown, card and icons."""
    from . import ability_template as AT
    ctl = CONTROLLERS[ab.slot]
    try:
        HF.fill_slot(ef, hero_common, ctl, seed=seed)
        lent = AT.lend(ef, hero_common, read or _corpus_read, ab.template, slot_ctl=ctl,
                       seed=seed, sink=HF.KIT_EVENT)
        ef.set_ref(ctl, "ref_2", lent.entry)
        _button(ef, ab, ctl)
    except (AT.TemplateError, EntityEditError, HF.FrameError, P.PartError) as e:
        raise AbilityError(f"ability {ab.slot}: {e}") from e
    return lent.entry


def build(ef: EntityFile, hero_common: EntityFile, ab: Ability, *, seed: str,
          with_indicator: bool = True, read=None) -> str:
    """Write ``ab`` into the hero ``ef``; returns its state's name."""
    word = ab.slot.title()
    group = f"Ability {word}"
    tag = f"{word} Ability"
    if ab.template is not None:
        return build_template(ef, hero_common, ab, seed=seed, read=read)
    if ab.combo:
        try:
            state = build_combo(ef, hero_common, ab, seed=seed, tag=tag, group=group)
            _button(ef, ab, CONTROLLERS[ab.slot])
        except (EntityEditError, HF.FrameError, P.PartError) as e:
            raise AbilityError(f"ability {ab.slot}: {e}") from e
        return state
    length = ab.duration if ab.duration is not None else HF.clip_length(ab.clip)
    if not length:
        raise AbilityError(f"ability {ab.slot}: the game has no clip {ab.clip!r}")
    try:
        # The clip and the aim, laid out as the base's own dash.
        ef.clone([f"Ability Dash\\{n}" for n in _CLIP], seed=f"{seed}:{ab.slot}:clip",
                 rename={n: n.replace("Dash Ability", tag) for n in _CLIP},
                 group={"Ability Dash": group}, source=hero_common)
        look = LOOK_AT
        ef.clone([look], seed=f"{seed}:{ab.slot}:look", rename={look: f"{tag} Look At"},
                 group={hero_common.component(look).group: group}, source=hero_common)
        HF._set_clips(ef, f"{tag} Anim", [ab.clip])
        HF._set_duration(ef, f"{tag} Anim", length)
        # Its root motion: copied from the base's empty dash slot it is 0, and
        # a clip that travels (a lunge, a leap) played in place.
        if ab.root_motion is not None:
            ef.set_value(f"{tag} Anim", HF.ROOT_MOTION, ab.root_motion)
        else:
            # Read through the hero's own copy of the selector (its links into
            # Hero_Common stay, which the hero inherits by alias): a number
            # slot is re-pointed only at a part of this file.
            if not any(c.name == OWN_ROOT_MOTION for c in ef.graph().components):
                sel = hero_common.component(ROOT_MOTION_SELECTOR)
                ef.clone([sel.path], rename={ROOT_MOTION_SELECTOR: OWN_ROOT_MOTION},
                         group={sel.group: "Ability Common"}, seed=f"{seed}:root-motion",
                         source=hero_common)
            ef.set_value(f"{tag} Anim", HF.ROOT_MOTION, 1.0)
            ef.set_ref(f"{tag} Anim", HF.ROOT_MOTION, OWN_ROOT_MOTION)
        snd = (own_sound(ef, ab.sound, name=f"{tag} Sound", group=group,
                         seed=f"{seed}:{ab.slot}:sound") if ab.sound else "")
        own_timeline(ef, f"{tag} Anim", length, sound=snd)
        w = TW.TalentWriter(ef, f"{seed}:{ab.slot}", group)
        state = f"State {tag}"
        timers = hits(ef, hero_common, w, ab.hits, tag=tag, group=group,
                      seed=f"{seed}:{ab.slot}", kind=ab.slot)
        aim = TW.link_to(ef, f"{tag} Look At")
        state_link = w.state(state, while_active=[TW.link_to(ef, f"{tag} Clip Selector"),
                                                  *([] if ab.has("look_enter") else [aim])],
                             flags=TW.PERSISTENT)
        if ab.has("look_enter"):
            ef.add_ref(state, "on_enter?", f"{tag} Look At")
        # The rush's root motion stops at an enemy only while the detector
        # its selector reads is held on (see IN_RANGE_DETECTOR).
        if ab.root_motion is None or ab.strike:
            _hold_in_range(ef, hero_common, state)
        if ab.intangible:
            _hold_intangible(state, ef)
        rush_end, window_timer = _NONE, ""
        if ab.strike:
            rush_end, window_timer = _build_strike(
                ef, hero_common, w, ab, tag=tag, group=group, state=state,
                hit_timers=timers, seed=seed)
            timers = [window_timer]                 # the hits are the strike's
        _timer(w, f"{tag} End Timer", length, on_end=rush_end,
               ends=_NONE if ab.has("no_end_state", "bare") else state_link)
        statuses(ef, ab.hits, tag=tag, switch=f"State {tag} Strike" if ab.strike else state,
                 seed=f"{seed}:{ab.slot}")
        if with_indicator:
            add_indicator(ef, ab, seed=seed)
        if ab.moving:
            split = hero_common.component(SPLIT_ENABLE)
            ef.add_external_ref(state, "while_active", split.guid,
                                f"[{HF.kind_label(split.cls)}] {hero_common.name}\\{split.path}")
        for t in [*timers, f"{tag} End Timer"]:
            ef.add_ref(state, "activates", t)
        # Hand the body to the ability: every shipped ability state (Geppetto's
        # basic attack and power, Hero_Common's own dash) activates the shared
        # move-inertia tester on entry (unconfirmed as the freeze's cause; see
        # Ability.variant).
        mi = hero_common.component(MOVE_INERTIA)
        if ab.has("no_inertia", "bare"):
            mi = None
        if mi is not None:
            ef.add_external_ref(state, "activates", mi.guid,
                                f"[{HF.kind_label(mi.cls)}] {hero_common.name}\\{mi.path}")
        ef.set_ref(f"{tag} Clip", "ref_11", state)
        # The button: the base's controller slot, pointed at this state.
        ctl = CONTROLLERS[ab.slot]
        HF.fill_slot(ef, hero_common, ctl, seed=seed)
        ef.set_ref(ctl, "ref_2", state)
        _bisect_state(ef, hero_common, ab, ctl=ctl, state=state, tag=tag, group=group,
                      timers=[*timers, f"{tag} End Timer"], seed=seed)
        _button(ef, ab, ctl)
        if ab.moving:
            for fld in MOVING_SWITCHES:
                ef.set_value(ctl, fld, False)
    except (EntityEditError, HF.FrameError, P.PartError) as e:
        raise AbilityError(f"ability {ab.slot}: {e}") from e
    return state
