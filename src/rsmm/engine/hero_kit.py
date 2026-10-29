"""A custom hero's ``kit``: building blocks the hero builder writes, expanded
into ``engine/ability_edit.py`` steps at build time.

The kit is declarative, so a mod stays data and a friend can write it by hand::

    [content.kit]
    form    = "wolf"                   # alt-form heroes (Scarlet): always wolf
    dash    = "none"                   # any slot can be "none"
    power   = { fire = "Enemies/Tentacle_Nightmares/Projectile_Tentacle_Nightmare_Laser_Shot" }
    special = { fire = "...", when = "Event Wolf Secondary Ability Active" }

Each block finds what it needs in the base's own entity by pattern rather than
from a per-hero table, so it works on any base that has the parts, and refuses
with the reason on one that does not:

* ``form = "wolf"``: the Blood Wolf recipe (a community manifest, PROVEN in game
  2026-10-29: a wolf in the run, preview fixed by the in-run gate). Scarlet's
  init fires the transformation, only outside the select screen (Hero_Common's
  own "not in preview" check), and both ways back are cut: the passive (night)
  transform and the trait button. ``"human"`` cuts the same two without the
  init transform (hood-test, unplaytested).
* ``<slot> = "none"``: every link in the hero's files to that slot's ability
  controller (``Dash Controller Selector``, ``Alt Primary Ability Controller``,
  ...) is removed. A base whose abilities are switched on only in Hero_Common
  has none to cut.
* ``<slot> = { fire = <entity> }``: a copy of the hero's own projectile spawner
  (its aim parts are the hero's, so they stay bound) aimed at ``entity`` (any
  shipped entity: an enemy projectile, another hero's) and fired when the
  slot's ability goes off: the slot group's ``Event ... Active`` state (the
  Wolf/Alt variant under ``form = "wolf"``), or ``when``. Whether an ENEMY
  projectile fired this way hurts enemies is unproven.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field

from . import entity_fields as EF
from . import entity_graph as EG

#: Kit slot -> the group word the engine uses, and the controller's name.
SLOTS = {
    "attack": ("Basic", "Basic Attack"),
    "power": ("Primary", "Primary Ability"),
    "special": ("Secondary", "Secondary Ability"),
    "defense": ("Defensive", "Defensive Ability"),
    "ultimate": ("Ultimate 1", "Ultimate Power"),
    "ultimate2": ("Ultimate 2", "Ultimate Power"),
    "trait": ("Trait", "Trait Ability"),
    "dash": ("Dash", "Dash"),
}
FORMS = ("wolf", "human")
_KEYS = {"form", *SLOTS}
_PREVIEW_GATE = "Activate Hero Controller Tester"     # Hero_Common: on only in a run


class KitError(ValueError):
    pass


@dataclass
class Copy:
    """A projectile of the hero's own: ``source`` copied to ``ref``, each of its
    reads of its owner hero (``reads``: get-value part -> value part in this
    hero) pointed at this hero instead. Built by :func:`build_copy` once the
    hero's own entity exists."""
    source: str
    ref: str
    reads: dict[str, str]


@dataclass
class _Ctx:
    hid: str
    folder: str
    copies: list[Copy] = field(default_factory=list)


def expand(kit: dict, main: bytes, name: str, *, hid: str = "Kit",
           copies: list[Copy] | None = None) -> list[dict]:
    """``kit`` as ability steps on ``main`` (the base's gameplay entity).
    Projectile copies it needs are appended to ``copies``."""
    ctx = _Ctx(hid, name, copies if copies is not None else [])
    if not isinstance(kit, dict):
        raise KitError("kit is a table")
    unknown = set(kit) - _KEYS
    if unknown:
        raise KitError(f"kit has no {', '.join(sorted(unknown))}; "
                       f"it takes form, {', '.join(SLOTS)}")
    g = EG.parse(main, name)
    names = {c.name for c in g.components}
    steps: list[dict] = []
    form = kit.get("form")
    if form is not None:
        steps += _form(str(form), names)
    for slot in SLOTS:
        if slot not in kit:
            continue
        v = kit[slot]
        if v == "none":
            steps += _remove(slot, g)
        elif isinstance(v, dict) and set(v) <= {"fire", "when"} and v.get("fire"):
            steps += _fire(slot, v, g, form == "wolf", ctx)
        elif isinstance(v, dict) and set(v) <= {"steps", "when", "replace"}:
            steps += _moves(slot, v, g, form == "wolf", ctx)
        else:
            raise KitError(f"kit {slot} = {v!r}: \"none\", or "
                           "{ fire = <entity> }, or { steps = [...], replace = true }")
    return steps


def _form(form: str, names: set[str]) -> list[dict]:
    if form not in FORMS:
        raise KitError(f"kit form = {form!r}: one of {', '.join(FORMS)}")
    need = {"Child Event Initialize", "Passive Transform Tester",
            "Event Trait Ability Transform", "State Alt Form Abilities Enabled"}
    if need - names:
        raise KitError("kit form: this base does not switch forms the way Scarlet does "
                       f"(no {', '.join(sorted(need - names))})")
    steps: list[dict] = [
        {"remove_link": "Child Event Initialize.activates", "to": "Passive Transform Tester"},
        {"link": "Passive Transform Tester.on_true", "to": ""},
        {"remove_link": "State Alt Form Abilities Enabled.activates",
         "to": "Trait Ability Controller"},
    ]
    if form == "wolf":
        gate = "Wolf Lock In Run Tester"
        steps[1:1] = [
            {"clone": [_PREVIEW_GATE], "from": "Hero_Common", "rename": {_PREVIEW_GATE: gate}},
            {"link": f"{gate}.on_true", "to": "Event Trait Ability Transform"},
            {"add_link": "Child Event Initialize.activates", "to": gate},
        ]
    return steps


def _remove(slot: str, g: EG.EntityGraph) -> list[dict]:
    word = re.escape(SLOTS[slot][1])
    want = re.compile(rf"^(Alt )?{word}( Power)?( Controller| Controller \d| Controller Selector)$")
    steps = []
    for c in g.components:
        for f in EF.fields(c):
            if f.kind != "ref[]":
                continue
            for it in f.items:
                last = it.text.rstrip().rsplit("\\", 1)[-1].removesuffix('""')
                if want.match(last):
                    steps.append({"remove_link": f"{c.name}.{f.name}", "to": last})
    if not steps:
        raise KitError(f"kit {slot} = \"none\": this base switches its {slot} on outside "
                       "its own files (Hero_Common), so there is no link to cut")
    return steps


def _trigger(slot: str, spec: dict, g: EG.EntityGraph, wolf: bool) -> str:
    """The state that goes off when ``slot``'s ability is used."""
    states = {c.name for c in g.components if c.cls == "oCEntityCpntStateSettings"}
    when = spec.get("when")
    if when is None:
        word = SLOTS[slot][0]
        groups = [f"Ability Wolf {word}", f"Ability Alt {word}"] if wolf else []
        groups.append(f"Ability {word}")
        for grp in groups:
            # Best first: the event that fires as the ability goes off, a state
            # that is on while it is active, then the slot's main state (every
            # slot has one; its `activates` fire as the ability starts). What
            # reacts to a hit or a kill, or only looks or steers, never starts it.
            cands = [c.name for c in g.components if c.group == grp
                     and c.cls == "oCEntityCpntStateSettings"
                     and not re.search(r"\bOn\b|Fx|Destroy|Control|Camera|Loop|Move|Killed|"
                                       r"Impact|Flag", c.name)]
            ranked = ([n for n in cands if re.match(r"^Event .*(Active|Activate|Shoot)$", n)]
                      + [n for n in cands if re.match(r"^State .*Active$", n)]
                      + sorted((n for n in cands if n.startswith("State ")), key=len))
            if ranked:
                when = ranked[0]
                break
    if when is None:
        raise KitError(f"kit {slot}: found no 'Event ... Active' state for it; "
                       "name the state to fire on with when = \"...\"")
    if when not in states:
        raise KitError(f"kit {slot}: when = {when!r} is not a state of this hero")
    return str(when)


def _fire(slot: str, spec: dict, g: EG.EntityGraph, wolf: bool, ctx: _Ctx) -> list[dict]:
    """The simple form: ``{ fire = <entity> }`` is a one-step timeline."""
    return _moves(slot, {"when": spec.get("when"), "steps": [{"fire": spec["fire"]}]}, g,
                  wolf, ctx)


# ---- a built ability: a timeline of blocks --------------------------------------
#
#   power = { replace = true, steps = [
#       { anim = "Characters\\Heroes\\RED\\Animations\\...\\RED_Wolf_Howl.fbx" },
#       { fire = "Enemies/.../Laser_Shot", angles = [-20, 0, 20] },
#       { wait = 0.3 },
#       { repeat = 3, every = 0.2, steps = [ { fire = "..." } ] },
#   ] }
#
# Built from parts the base already has, found by kind rather than by name:
# its projectile spawner and the 3D node it aims through (one copy per angle,
# the node's yaw set: through its Y-angle value where it has one, the way Piper
# fans her notes, PROVEN 2026-09-26; else its inline yaw, UNPROVEN), a plain
# number (for angles and delays), a timer and an empty state (one pair per
# moment after the first, as attack_build's beats). `replace` cuts the slot's
# own hits and spawns from its trigger, keeping its animation and flow.

#: Every projectile inherits Projectile_Model, whose generic numbers a spawner
#: value sets per shot (Scarlet's dash daggers set Damage Multiplier Default
#: this way). Option -> (its value, min, max, scale to the game's unit).
PROJ_MODEL = "Projectile_Model\\Projectile_Model.entity.ot"
PROJ_VALUES = {
    "damage": ("Damage Multiplier Default", 0.0, 5000.0, 0.01),     # % of a hit
    "lifetime": ("Lifetime Duration", 0.05, 30.0, 1.0),
    "size": ("Spawner Scale Value", 0.1, 10.0, 1.0),
    "knockback": ("Pushback Value", 0.0, 50.0, 1.0),
    "stagger": ("Stagger Multiplier Default", 0.0, 100.0, 1.0),
    "explode": ("Splash Radius Value", 0.5, 30.0, 1.0),              # + Splash Value 1
}
#: Status effects: option -> (flag value, duration value or None).
PROJ_STATUS = {
    "burn": ("Applies Ignite Debuff Flag", "Ignite Duration Value"),
    "poison": ("Applies Poison Debuff Flag", "Poison Duration Value"),
    "root": ("Applies Root Debuff Flag", "Root Duration Value"),
    "curse": ("Applies Curse Debuff Flag", None),
    "vulnerable": ("Applies Hero Is Vulnerable Debuff Flag", None),
}

#: Ricochet: Juliet's projectiles (all inheriting this base) bounce to the next
#: enemy as many times as a spawner value says (her Skill Defense Ricochet
#: talent sets it; nothing reads the owner), each bounce at its own damage.
RICOCHET_BASE = "Heroes\\Hero_Juliet\\Hero_Juliet_Spawned_Attack_Base.entity.ot"
RICOCHET_COUNT = "Skill Defense Ricochet Number"
RICOCHET_DAMAGE = "Skill Defense Ricochet Damage Multiplier"
#: A whole-number spawner value to copy when the base has none (Scarlet):
#: Juliet's, every link of which is re-pointed, so nothing stays hers.
INT_SV_DONOR = ("Juliet", "Common Ability Modifier Type Spawner Value")

STEP_KEYS = {"fire": {"fire", "angles", "offsets", "speed", "ricochet", "ricochet_damage", "reads",
                      *PROJ_VALUES, *PROJ_STATUS},
             "wait": {"wait"}, "repeat": {"repeat", "every", "steps"},
             "anim": {"anim"}, "hit": {"hit"}, "heal": {"heal"}}

#: A hit area is a shipped hero AOE spawned at that moment, its numbers set per
#: spawn by spawner values (how Kintaro's bear spawns this very entity: Damage
#: Multiplier + Radius + From Bear). Self-contained: zone attack, damage,
#: effects, its own delay and despawn.
HIT_ENTITY = "Heroes\\Hero_Kintaro\\Hero_Kintaro_Special_Delayed_AOE.entity.ot"
HIT_VALUES = {"radius": ("Skill Special Delayed AOE Radius", 3.5, 0.5, 30.0, 1.0),
              "damage": ("Skill Special Delayed AOE Damage Multiplier", 100.0, 0.0, 5000.0, 0.01),
              "delay": ("Skill Special Delayed AOE Delay Duration", 0.0, 0.0, 10.0, 1.0)}
_HITS = {"oCEntityCpntGpnTargetAttackSettings", "oCEntityCpntZoneAttackSettings",
         "oCEntityCpntEntitySpawnerSettings", "oCEntityCpntContinuousAttackSettings",
         "oCEntityAttackEntityCpntSettings"}
_YAW = 8                                   # node obj_4: literal 8 is the Y angle


def timeline(steps, t: float = 0.0) -> list[tuple[float, dict]]:
    """``steps`` unrolled to ``(seconds after the trigger, block)``."""
    if not isinstance(steps, list) or not all(isinstance(x, dict) for x in steps):
        raise KitError("steps is a list of blocks")
    out = []
    for n, st in enumerate(steps, 1):
        kind = next((k for k in STEP_KEYS if k in st), None)
        if kind is None or set(st) - STEP_KEYS[kind]:
            raise KitError(f"step {n} {st!r}: one of fire, hit, heal, wait, repeat, anim "
                           "(with its own keys only)")
        if kind == "wait":
            w = st["wait"]
            if isinstance(w, bool) or not isinstance(w, (int, float)) or not 0 <= w <= 30:
                raise KitError(f"step {n}: wait is 0..30 seconds")
            t += float(w)
        elif kind == "repeat":
            times, every = st["repeat"], st.get("every", 0.2)
            if isinstance(times, bool) or not isinstance(times, int) or not 1 <= times <= 20:
                raise KitError(f"step {n}: repeat is 1..20 times")
            if isinstance(every, bool) or not isinstance(every, (int, float)) or every < 0:
                raise KitError(f"step {n}: every is the seconds between repeats")
            for i in range(times):
                out += timeline(st.get("steps") or [], t + i * float(every))
            t += times * float(every)
        else:
            if kind == "fire":
                for k, (_, lo, hi, _) in PROJ_VALUES.items():
                    v = st.get(k)
                    if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                          or not lo <= v <= hi):
                        raise KitError(f"step {n}: {k} is {lo:g}..{hi:g}")
                for k in PROJ_STATUS:
                    v = st.get(k)
                    if v is not None and not (v is True or (not isinstance(v, bool)
                                                            and isinstance(v, (int, float))
                                                            and 0 < v <= 60)):
                        raise KitError(f"step {n}: {k} is true or its seconds (0..60)")
                for k, hi in (("ricochet", 20), ("ricochet_damage", 5000)):
                    v = st.get(k)
                    if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                          or not 0 <= v <= hi or (k == "ricochet" and v != int(v))):
                        raise KitError(f"step {n}: {k} is 0..{hi}"
                                       + (" (whole bounces)" if k == "ricochet" else " (%)"))
                sp = st.get("speed")
                if sp is not None and (isinstance(sp, bool) or not isinstance(sp, (int, float))
                                       or not 0 <= sp <= 200):
                    raise KitError(f"step {n}: speed is 0..200")
            if kind == "heal":
                v = st["heal"]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 10000:
                    raise KitError(f"step {n}: heal is an amount above 0")
            if kind == "hit":
                h = st["hit"]
                if not isinstance(h, dict) or set(h) - set(HIT_VALUES):
                    raise KitError(f"step {n}: hit is {{ radius, damage, delay }}")
                for k, (_, _, lo, hi, _) in HIT_VALUES.items():
                    v = h.get(k)
                    if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                          or not lo <= v <= hi):
                        raise KitError(f"step {n}: hit {k} is {lo:g}..{hi:g}")
            out.append((round(t, 4), st))
    return out


def _moves(slot: str, spec: dict, g: EG.EntityGraph, wolf: bool, ctx: _Ctx) -> list[dict]:
    trigger = _trigger(slot, spec, g, wolf)
    plan = timeline(spec.get("steps") or [])
    if not any("fire" in b or "hit" in b or "heal" in b for _, b in plan):
        return _replace(trigger, g) if spec.get("replace") else []
    by = {c.guid: c for c in g.components}

    def pick(test, what: str) -> EG.Component:
        c = next((c for c in g.components if test(c)), None)
        if c is None:
            raise KitError(f"kit {slot}: this base has no {what} to build from")
        return c

    def node_of(c):
        return next((by[r.guid] for r in c.refs if r.guid in by
                     and by[r.guid].cls == "oCEntityCpnt3dNodeSettings"), None)

    aimed = [c for c in g.components
             if c.cls == "oCEntityCpntEntitySpawnerSettings" and node_of(c)]
    needs_spawner = any("fire" in b or "hit" in b for _, b in plan)
    if not aimed and needs_spawner:
        raise KitError(f"kit {slot}: this base has no spawner aiming through a 3D node "
                       "to build from (Carmilla and Sun Wukong have none)")
    spawner = next((c for c in aimed if any("Projectile" in x for x in c.literals)),
                   aimed[0] if aimed else None)
    node = node_of(spawner) if spawner else None
    number = pick(lambda c: c.cls == "oCEntityCpntValueSettings"
                  and any(f.name == "value" and f.text.startswith("f32")
                          for f in EF.fields(c)), "plain number")
    timer = pick(lambda c: c.cls == "oCEntityCpntTimerSettings", "timer")
    empty = pick(lambda c: c.cls == "oCEntityCpntStateSettings" and not c.refs, "empty state")
    aim = _obj_refs(node, "obj_4") if node else []
    yaw_ref = next((i for i, r in enumerate(aim) if "Y Angle" in r), None)
    x_ref = next((i for i, r in enumerate(aim) if "X Offset" in r), None)
    n_values = sum(len(f.items) for f in EF.fields(spawner) if f.name == "spawner_values") \
        if spawner else 0
    sv_donor = next((c for c in g.components if c.cls == "oCEntityCpntSpawnerValueSettings"
                     and any(f.name == "value" and f.text.startswith("f32")
                             for f in EF.fields(c))), None)
    int_donor = next((c for c in g.components if c.cls == "oCEntityCpntSpawnerValueSettings"
                      and any(f.name == "value" and f.text.startswith("int")
                              for f in EF.fields(c))), None)

    tag = f"Kit {slot.title()}"
    steps: list[dict] = _replace(trigger, g) if spec.get("replace") else []
    made = 0

    def num(label: str, value: float) -> str:
        part = f"{tag} {label}"
        steps.extend([{"clone": [number.name], "rename": {number.name: part}},
                      {"set": f"{part}.value", "value": value}])
        return part

    def setv(sp: str, ent: str, label: str, target: str, value: float,
             whole: bool = False) -> None:
        """A spawner value: ``sp``'s spawn gets ``value`` in its ``target``
        (``whole``: a whole-number target, set by a whole-number copy)."""
        sv = f"{sp} {label}"
        if whole:
            donor = int_donor.name if int_donor else INT_SV_DONOR[1]
            clone = {"clone": [donor], "rename": {donor: sv}}
            if int_donor is None:
                clone["from"] = INT_SV_DONOR[0]
            steps.extend([clone,
                          {"link": f"{sv}.spawner", "to": sp},
                          {"retarget": f"{sv}.target_value", "node": f"{ent}|{target}"},
                          {"set": f"{sv}.value", "value": int(value)},
                          {"set": f"{sv}.template[1]", "value": ent}])
            if has_values:
                steps.append({"add_link": f"{sp}.spawner_values", "to": sv})
            return
        if sv_donor is None:
            raise KitError(f"kit {slot}: this base has no spawner value to copy")
        steps.extend([{"clone": [sv_donor.name], "rename": {sv_donor.name: sv}},
                      {"link": f"{sv}.spawner", "to": sp},
                      {"retarget": f"{sv}.target_value", "node": f"{ent}|{target}"},
                      {"set": f"{sv}.value", "value": float(value)},
                      {"set": f"{sv}.template[1]", "value": ent}])
        if has_values:
            steps.append({"add_link": f"{sp}.spawner_values", "to": sv})

    has_values = bool(spawner) and any(f.name == "spawner_values" for f in EF.fields(spawner))
    moments: dict[float, str] = {0.0: trigger}
    for t, block in plan:
        if not ("fire" in block or "hit" in block or "heal" in block):
            continue
        if t not in moments:
            k = len(moments)
            st, tm = f"{tag} Moment {k}", f"{tag} Moment {k} Timer"
            steps += [{"clone": [empty.name], "rename": {empty.name: st}},
                      {"clone": [timer.name], "rename": {timer.name: tm}},
                      # `set` works whether the copied timer's duration is a
                      # number or a link (the link becomes this number).
                      {"set": f"{tm}.duration", "value": t},
                      {"link": f"{tm}.on_tick", "to": st},
                      {"link": f"{tm}.on_end", "to": ""},
                      {"link": f"{tm}.state", "to": ""},
                      {"add_link": f"{trigger}.activates", "to": tm}]
            moments[t] = st
        if "heal" in block:
            # A copy of one of the hero's own health gains (resource 2: health;
            # 3 reads as a share of max health), its amount set.
            gains = [c for c in g.components if c.cls == "oCDtEntityCpntResourceGainSettings"
                     and any(f.name == "bytes_1" and f.text[:2] in ("02", "03")
                             for f in EF.fields(c))]
            if not gains:
                raise KitError(f"kit {slot}: this base has no heal to copy (the Snow Queen "
                               "heals no one)")
            donor = sorted(gains, key=lambda c: next(f.text for f in EF.fields(c)
                                                     if f.name == "bytes_1"))[0]
            made += 1
            hp = f"{tag} Heal {made}"
            steps += [{"clone": [donor.name], "rename": {donor.name: hp}},
                      {"set": f"{hp}.value_2", "value": float(block["heal"])},
                      {"add_link": f"{moments[t]}.activates", "to": hp}]
            continue
        if "hit" in block:
            if sv_donor is None:
                raise KitError(f"kit {slot}: this base has no spawner value to copy for a hit")
            made += 1
            sp, nd = f"{tag} Hit {made}", f"{tag} Hit {made} Aim"
            steps += [{"clone": [spawner.name, node.name],
                       "rename": {spawner.name: sp, node.name: nd}},
                      {"set": f"{sp}.template[1]", "value": HIT_ENTITY}]
            steps += [{"remove_link": f"{sp}.spawner_values[0]"}] * n_values
            for key, (target, default, _, _, scale) in HIT_VALUES.items():
                setv(sp, HIT_ENTITY, key.title(), target,
                     float(block["hit"].get(key, default)) * scale)
            steps.append({"add_link": f"{moments[t]}.activates", "to": sp})
            continue
        ent = _entity_ref(block["fire"])
        shot = _copy_for(ent, block.get("reads") or {}, steps, ctx, slot)
        angles = block.get("angles") or [0]
        offsets = block.get("offsets") or []
        for what, xs in (("angles", angles), ("offsets", offsets)):
            if not isinstance(xs, list) or not all(
                    isinstance(a, (int, float)) and not isinstance(a, bool) for a in xs):
                raise KitError(f"kit {slot}: {what} is a list of numbers, e.g. [-20, 0, 20]")
        if offsets and angles == [0]:
            angles = [0] * len(offsets)          # parallel: one straight shot per offset
        if offsets and len(offsets) != len(angles):
            raise KitError(f"kit {slot}: give one offset per direction")
        for n_shot, deg in enumerate(angles):
            made += 1
            sp, nd = f"{tag} Shot {made}", f"{tag} Shot {made} Aim"
            steps += [{"clone": [spawner.name, node.name],
                       "rename": {spawner.name: sp, node.name: nd}},
                      {"set": f"{sp}.template[1]", "value": shot}]
            steps += [{"remove_link": f"{sp}.spawner_values[0]"}] * n_values
            if deg:
                rad = math.radians(float(deg))
                if yaw_ref is not None:
                    yaw = num(f"Shot {made} Yaw", rad)
                    steps.append({"link": f"{nd}.obj_4[{yaw_ref}]", "to": yaw})
                else:
                    steps.append({"set": f"{nd}.obj_4[{_YAW}]", "value": rad})
            if offsets and offsets[n_shot]:
                # Side offset (metres): the node's inline X (literal 3), or its
                # X-offset value where it has one (Piper's fan).
                if x_ref is not None:
                    xo = num(f"Shot {made} Side", float(offsets[n_shot]))
                    steps.append({"link": f"{nd}.obj_4[{x_ref}]", "to": xo})
                else:
                    steps.append({"set": f"{nd}.obj_4[3]", "value": float(offsets[n_shot])})
            if block.get("speed") is not None:
                steps.append({"set": f"{sp}.speed?", "value": float(block["speed"])})
            if _is_projectile(ent):
                for key, (target, _, _, scale) in PROJ_VALUES.items():
                    if block.get(key) is not None:
                        setv(sp, PROJ_MODEL, key.title(), target, float(block[key]) * scale)
                if block.get("explode") is not None:
                    setv(sp, PROJ_MODEL, "Explodes", "Splash Value", 1.0)
                for key, (flag, dur) in PROJ_STATUS.items():
                    v = block.get(key)
                    if v:
                        setv(sp, PROJ_MODEL, key.title(), flag, 1.0)
                        if dur and v is not True:
                            setv(sp, PROJ_MODEL, f"{key.title()} Time", dur, float(v))
                if block.get("ricochet"):
                    if not _inherits(ent, b"Hero_Juliet_Spawned_Attack_Base"):
                        raise KitError(f"kit {slot}: ricochet needs one of Juliet's projectiles "
                                       f"(they bounce); {block['fire']} is not one")
                    setv(sp, RICOCHET_BASE, "Ricochet", RICOCHET_COUNT, block["ricochet"],
                         whole=True)
                    setv(sp, RICOCHET_BASE, "Ricochet Damage", RICOCHET_DAMAGE,
                         float(block.get("ricochet_damage", 100)) * 0.01)
            elif any(block.get(k) is not None for k in (*PROJ_VALUES, *PROJ_STATUS)):
                raise KitError(f"kit {slot}: {block['fire']} is not a projectile "
                               "(Projectile_Model); damage, lifetime and effects need one")
            steps.append({"add_link": f"{moments[t]}.activates", "to": sp})
    return steps


def _is_projectile(ent: str) -> bool:
    """Whether ``ent`` inherits Projectile_Model (its generic numbers apply)."""
    return _inherits(ent, b"Projectile_Model\\")


def _inherits(ent: str, needle: bytes) -> bool:
    from . import entity_check as CK
    raw = CK._corpus_reader(ent)
    return bool(raw) and needle in raw


def _obj_refs(c: EG.Component, fld: str) -> list[str]:
    """The names an object field's links point at, in order."""
    f = next((x for x in EF.fields(c) if x.name == fld), None)
    return re.findall(r"<- \[[^\]]+\] ([^<']+?)(?=\s+<-|\s+'|$)", f.text) if f else []


def _replace(trigger: str, g: EG.EntityGraph) -> list[dict]:
    """Cut what the slot's trigger hits and spawns, so only the timeline does."""
    by = {c.guid: c for c in g.components}
    t = next(c for c in g.components if c.name == trigger)
    out = []
    for f in EF.fields(t):
        if f.kind != "ref[]":
            continue
        for it in f.items:
            last = it.text.rstrip().rsplit("\\", 1)[-1].removesuffix('""')
            hit = next((c for c in by.values() if c.name == last), None)
            if hit is not None and hit.cls in _HITS:
                out.append({"remove_link": f"{trigger}.{f.name}", "to": last})
    return out


def _entity_ref(path) -> str:
    ent = str(path).replace("/", "\\").strip("\\").removeprefix("EntitySettings\\")
    return ent if ent.endswith(".entity.ot") else ent.removesuffix(".entity") + ".entity.ot"


def anim_swaps(kit: dict, main: bytes, name: str) -> dict[str, str]:
    """``{slot's clip: new clip}`` for every ``anim`` block: the hero kind's
    ``references`` swap, in this hero's own files only. A clip of the same
    hero keeps the skeleton (another hero's bones would not move it)."""
    g = EG.parse(main, name)
    wolf = kit.get("form") == "wolf"
    clips = set(hero_clips(main))
    out: dict[str, str] = {}
    for slot in SLOTS:
        v = kit.get(slot)
        if not isinstance(v, dict):
            continue
        new = [b["anim"] for _, b in timeline(v.get("steps") or []) if "anim" in b]
        if not new:
            continue
        if new[-1] not in clips:
            raise KitError(f"kit {slot}: anim {new[-1]!r} is not one of this hero's clips")
        word = SLOTS[slot][0]
        groups = ([f"Ability Wolf {word}"] if wolf else []) + [f"Ability {word}"]
        old = next((m.group(0).decode() for grp in groups for c in g.components
                    if c.group == grp and c.cls == "oCEntityCpntAnimaticSettings"
                    for m in [re.search(rb"Characters\\[^\x00\"]+?\.fbx", c.body)] if m), None)
        if old is None:
            raise KitError(f"kit {slot}: found no animation on this slot to swap")
        out[old] = new[-1]
    return out


def hero_clips(main: bytes) -> list[str]:
    """Every animation clip the hero's gameplay entity plays."""
    return sorted({m.decode() for m in re.findall(
        rb"Characters\\[^\x00\"]*?\\Animations\\[^\x00\"]+?\.fbx", main)})


# ---- projectiles of the hero's own ---------------------------------------------
#
# Some projectiles take their behaviour from the hero that fired them: Kintaro's
# axe reads its rebounds, timeout and reach from Kintaro, the Snow Queen's shard
# whether seeking (each hit refreshing its lifetime) is on. Fired by anyone else
# those reads find nothing. So such a projectile is fired as a COPY whose reads
# point at numbers in this hero (the same owner + template + value read the
# original does, aimed at this hero), each the original hero's own number
# unless the block's `reads` says otherwise.

#: Value parts to copy for a read's number, by type (none links anywhere).
_READ_DONORS = {"f32": "Lifetime Duration", "int": "Ignite Value",
                "bool": "Can Destroy Projectile Through"}


def read_label(getvalue: str) -> str:
    """``Owner Max Rebound Get Value`` -> ``Max Rebound``."""
    return re.sub(r"^Owner |\s*Get Value$", "", getvalue).strip()


def owner_reads(ent: str) -> list[dict]:
    """What projectile ``ent`` reads from its owner hero: ``{part, label, hero,
    type, default}`` per read, the default being that hero's own number."""
    from . import entity_check as CK
    raw = CK._corpus_reader(ent)
    if raw is None:
        return []
    out = []
    for c in EG.parse(raw).components:
        if c.cls != "oCEntityCpntGetValueSettings":
            continue
        hero = next((x for x in c.literals
                     if x.startswith("Heroes\\") and x.endswith(".entity.ot")), None)
        if hero is None or not c.refs:
            continue
        src = CK._corpus_reader(hero)
        target = next((x for x in EG.parse(src).components if x.guid == c.refs[-1].guid),
                      None) if src else None
        kind, default = "f32", 0.0
        if target is not None:
            v = next((f.text for f in EF.fields(target) if f.name == "value"), "")
            m = re.match(r"^(f32|int|bool) (\S+)", v)
            if m:
                kind = m[1]
                default = (m[2] == "True") if kind == "bool" else (
                    int(m[2]) if kind == "int" else float(m[2]))
        out.append({"part": c.name, "label": read_label(c.name), "hero": hero,
                    "type": kind, "default": default})
    return out


def _copy_for(ent: str, overrides: dict, steps: list[dict], ctx: _Ctx, slot: str) -> str:
    """The ref to fire for ``ent``: itself, or a copy of the hero's own when it
    reads its owner (its numbers added to ``steps`` as value parts)."""
    reads = owner_reads(ent)
    if not reads:
        if overrides:
            raise KitError(f"kit {slot}: {ent} reads nothing from its hero; drop `reads`")
        return ent
    labels = {r["label"]: r for r in reads}
    bad = set(overrides) - set(labels)
    if bad:
        raise KitError(f"kit {slot}: {ent} reads {', '.join(labels)} from its hero, "
                       f"not {', '.join(sorted(bad))}")
    k = len(ctx.copies) + 1
    ref = f"Heroes\\{ctx.folder}\\Hero_{ctx.hid}_Kit{k}.entity.ot"
    parts = {}
    for r in reads:
        part = f"Kit Copy {k} {r['label']}"
        donor = _READ_DONORS[r["type"]]
        v = overrides.get(r["label"], r["default"])
        if r["type"] == "bool":
            v = bool(v)
        elif r["type"] == "int":
            v = int(v)
        steps.extend([{"clone": [donor], "from": "Projectile_Model/Projectile_Model",
                       "rename": {donor: part}},
                      {"set": f"{part}.value", "value": v}])
        parts[r["part"]] = part
    ctx.copies.append(Copy(ent, ref, parts))
    return ref


def reader(copies: list[Copy]):
    """The corpus reader, answering a copy's ref with its source (what the
    ability check and spawner values need to know of it)."""
    from . import entity_check as CK
    src = {c.ref: c.source for c in copies}
    return lambda ref: CK._corpus_reader(src.get(ref, ref))


def build_copy(copy: Copy, main: bytes, main_ref: str) -> bytes:
    """``copy``'s bytes: its source with each owner read aimed at this hero
    (``main``, its final gameplay entity at ``main_ref``)."""
    from . import entity_check as CK
    from .entity_graph_edit import EntityFile
    raw = CK._corpus_reader(copy.source)
    if raw is None:
        raise KitError(f"{copy.source} is not in the game files")
    stem = copy.ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    ef = EntityFile(raw, stem)
    hero = {c.name: c for c in EG.parse(main).components}
    main_stem = main_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    for gv, part in copy.reads.items():
        v = hero.get(part)
        if v is None:
            raise KitError(f"the hero has no {part!r} for {stem} to read")
        ef.set_value(gv, "template[1]", main_ref)
        label = f"[Value] {main_stem}\\" + (f"{v.group}\\" if v.group else "") + v.name
        point(ef, gv, "value", v.guid, label)
    return ef.to_bytes()


def point(ef, part: str, fld: str, guid: bytes, label: str) -> None:
    """Write ``part.fld``'s link as ``guid``/``label`` whatever it held (empty,
    or another kind): a spawner value's target, a get-value's value."""
    from .entity_graph_edit import _B, _E, _lstr
    c, f, _ = ef._field(part, fld)
    a, b = ef._picker_span(c, f)
    picker = [x.name for x in ef.cf.classes].index("oCEntityCpntPicker")
    new = _B + struct.pack("<I", picker) + guid + _lstr(label) + _E
    ef._splice(c, len(ef.objects[c.index - 1]) - len(c.body) + a,
               len(ef.objects[c.index - 1]) - len(c.body) + b, new)
