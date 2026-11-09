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

from dataclasses import dataclass, field

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
    #: TEMPORARY playtest bisection (2026-11-08: states died within a frame):
    #: "no_end_state" = the end timer does not switch the state (its clip
    #: ends it, as the dash's does), "no_inertia" = no move-inertia hand-over,
    #: "bare" = both; "dash_state" / "released": see _bisect_state. Remove
    #: once the cause is known.
    variant: str = ""
    #: The basic attack as shipped heroes do it: a combo of steps, each its
    #: own clip whose TIMELINE lands the hit (see build_combo / COMBO_STEP_KEYS).
    combo: list = field(default_factory=list)

    @classmethod
    def parse(cls, slot: str, raw: dict) -> Ability:
        if slot not in CONTROLLERS:
            raise AbilityError(f"ability {slot!r}: one of {', '.join(CONTROLLERS)}")
        if isinstance(raw, dict) and raw.get("combo") and not raw.get("clip"):
            raw = {**raw, "clip": (raw["combo"][0] or {}).get("clip", "")}
        if not isinstance(raw, dict) or not raw.get("clip"):
            raise AbilityError(f"ability {slot}: needs clip = <animation>")
        unknown = set(raw) - {"clip", "cooldown", "duration", "hits", "bank", "name_key",
                              "desc_key", "indicator", "sound", "variant", "combo"}
        if unknown:
            raise AbilityError(f"ability {slot}: no {', '.join(sorted(unknown))}")
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
            if not isinstance(combo, list) or len(combo) != COMBO_STEPS \
                    or not all(isinstance(st, dict) for st in combo):
                raise AbilityError(f"ability {slot}: combo is a list of {COMBO_STEPS} steps")
            for n, st in enumerate(combo, 1):
                if set(st) - COMBO_STEP_KEYS or not st.get("clip"):
                    raise AbilityError(f"ability {slot}: combo step {n} is {{ clip, "
                                       f"{', '.join(sorted(COMBO_STEP_KEYS - {'clip'}))} }}")
                if len(_step_hits(st, f"ability {slot} combo step {n}")) != 1:
                    raise AbilityError(f"ability {slot}: combo step {n} lands one hit")
        return cls(slot, str(raw["clip"]), float(raw.get("cooldown", 1.0)),
                   float(raw["duration"]) if raw.get("duration") is not None else None,
                   hits, ind, str(raw.get("bank", "")), str(raw.get("name_key", "")),
                   str(raw.get("desc_key", "")), sound, str(raw.get("variant", "")),
                   [dict(st) for st in combo])


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
    if ab.variant not in ("dash_state", "released"):
        return
    if ab.variant == "dash_state":
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
    w = TW.TalentWriter(ef, f"{seed}:{ab.slot}", group)
    state = f"State {tag}"
    w.state(state)
    # its parent state and controller: the hero's (by the GUID the copied link
    # holds -- a controller link names the shared base's slot, not the donor's)
    mine = {f"State {pre}": state, "Basic Attack Controller": ctl}
    for r in ef.component(combo).refs:
        target = mine.get(r.path.rsplit("\\", 1)[-1])
        if target and r.path.split("] ", 1)[-1].startswith(donor.name + "\\"):
            ef.swap_refs(combo, r.guid, target)
    # The button and the state go through the combo SELECTOR, as the donor's
    # do: the combo switches its parent state on, so a state that started the
    # combo itself re-entered forever and hung the game on the first press
    # (playtest 2026-11-08). The selector's first entry is a talent finisher's
    # combo, picked while that talent's state is on: here the hero's own combo
    # behind a state of its own that nothing switches on, so the default
    # (its combo) is always the one picked.
    sel = f"{tag} Combo Selector"
    never = f"State {tag} Finisher Off"
    w.state(never)
    for r in ef.component(sel).refs:
        if r.path.split("] ", 1)[-1].startswith(donor.name + "\\"):
            ef.swap_refs(sel, r.guid, combo if r.path.startswith("[Dt Attack Combo]") else never)
    ef.add_ref(state, "on_enter?", sel)
    mi = hero_common.component(MOVE_INERTIA)
    ef.add_external_ref(state, "activates", mi.guid,
                        f"[{HF.kind_label(mi.cls)}] {hero_common.name}\\{mi.path}")
    ef.set_ref(ctl, "ref_2", sel)
    names = [x.name for x in ef.cf.classes]
    all_hits = []
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
        all_hits += step_hits
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
    statuses(ef, all_hits, tag=f"{tag} Combo", switch=state, seed=f"{seed}:{ab.slot}")
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
    ef.set_value(ctl, "value_4", float(ab.cooldown))
    if ab.slot == "attack":
        for fld, on in ATTACK_SWITCHES.items():
            ef.set_value(ctl, fld, on)
    if ab.desc_key:
        HF._set_text(ef, ctl, ab.bank, ab.desc_key)
    if ab.name_key:
        HF._set_text(ef, ctl, ab.bank, ab.name_key)


def build(ef: EntityFile, hero_common: EntityFile, ab: Ability, *, seed: str,
          with_indicator: bool = True) -> str:
    """Write ``ab`` into the hero ``ef``; returns its state's name."""
    word = ab.slot.title()
    group = f"Ability {word}"
    tag = f"{word} Ability"
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
        snd = (own_sound(ef, ab.sound, name=f"{tag} Sound", group=group,
                         seed=f"{seed}:{ab.slot}:sound") if ab.sound else "")
        own_timeline(ef, f"{tag} Anim", length, sound=snd)
        w = TW.TalentWriter(ef, f"{seed}:{ab.slot}", group)
        state = f"State {tag}"
        timers = hits(ef, hero_common, w, ab.hits, tag=tag, group=group,
                      seed=f"{seed}:{ab.slot}", kind=ab.slot)
        state_link = w.state(state, while_active=[TW.link_to(ef, f"{tag} Clip Selector"),
                                                  TW.link_to(ef, f"{tag} Look At")])
        _timer(w, f"{tag} End Timer", length,
               ends=_NONE if ab.variant in ("no_end_state", "bare") else state_link)
        statuses(ef, ab.hits, tag=tag, switch=state, seed=f"{seed}:{ab.slot}")
        if with_indicator:
            add_indicator(ef, ab, seed=seed)
        for t in [*timers, f"{tag} End Timer"]:
            ef.add_ref(state, "activates", t)
        # Hand the body to the ability: every shipped ability state (Geppetto's
        # basic attack and power, Hero_Common's own dash) activates the shared
        # move-inertia tester on entry (unconfirmed as the freeze's cause; see
        # Ability.variant).
        mi = hero_common.component(MOVE_INERTIA)
        if ab.variant in ("no_inertia", "bare"):
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
    except (EntityEditError, HF.FrameError, P.PartError) as e:
        raise AbilityError(f"ability {ab.slot}: {e}") from e
    return state
