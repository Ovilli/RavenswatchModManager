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
_KEYS = {"form", "pets", *SLOTS}
_PREVIEW_GATE = "Activate Hero Controller Tester"     # Hero_Common: on only in a run


class KitError(ValueError):
    pass


@dataclass
class Copy:
    """A projectile of the hero's own: ``source`` copied to ``ref``, each of its
    reads of its owner hero (``reads``: get-value part -> value part in this
    hero) pointed at this hero instead. Built by :func:`build_copy` once the
    hero's own entity exists. A summoned ally (``engine/ally_summon.py``) comes
    ready made: ``data`` is its bytes, identities included."""
    source: str
    ref: str
    reads: dict[str, str]
    data: bytes | None = None
    base: str | None = None
    #: A summon's own end (lifetime, burst), so two blocks summoning the same
    #: enemy differently get a copy each.
    end: tuple = ()
    #: A shipped entity spawned as it is (Piper's rat as a pet): nothing is
    #: written, its preload is borrowed.
    shipped: bool = False


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
    # After the slots: a talent-gated pets block holds off what they built.
    if kit.get("pets") is not None:
        steps += _pets(kit["pets"], g, form == "wolf", ctx, steps)
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

#: A summon's attack, untuned: (area, speed, debuffs, cooldown, reach, range);
#: see _tune_attack.
_NO_TUNING = (None, None, True, None, None, None)

STEP_KEYS = {"fire": {"fire", "angles", "offsets", "speed", "ricochet", "ricochet_damage", "reads",
                      *PROJ_VALUES, *PROJ_STATUS},
             "wait": {"wait"}, "repeat": {"repeat", "every", "steps"},
             "anim": {"anim"}, "hit": {"hit"}, "heal": {"heal"},
             "summon": {"summon", "lifetime", "burst", "burst_on_hit", "appear", "attack",
                        "attack_area", "attack_speed", "attack_debuffs", "attack_cooldown",
                        "attack_reach", "attack_range"}}

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
            raise KitError(f"step {n} {st!r}: one of fire, hit, heal, summon, wait, repeat, anim "
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
    if not any("fire" in b or "hit" in b or "heal" in b or "summon" in b for _, b in plan):
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
    needs_spawner = any("fire" in b or "hit" in b or "summon" in b for _, b in plan)
    if not aimed and needs_spawner:
        raise KitError(f"kit {slot}: this base has no spawner aiming through a 3D node "
                       "to build from (Carmilla and Sun Wukong have none)")
    spawner = next((c for c in aimed if any("Projectile" in x for x in c.literals)),
                   aimed[0] if aimed else None)
    node = node_of(spawner) if spawner else None
    number = pick(lambda c: c.cls == "oCEntityCpntValueSettings"
                  and any(f.name == "value" and f.text.startswith("f32")
                          for f in EF.fields(c)), "plain number")
    timer = pick(lambda c: c.cls == "oCEntityCpntTimerSettings" and c.override is None,
                 "timer")
    # A donor must be a part of its own, never an override: a clone keeps
    # the override mark, so every copy of Scarlet's "Event Initialize Starting
    # Modifiers" (an override of Character_Common's) replaced that one part
    # instead of being added, and the live hero had none of them (probe,
    # 2026-11-03: Kit Pet Spawn / Start / Order End all missing).
    empty = pick(lambda c: c.cls == "oCEntityCpntStateSettings" and not c.refs
                  and c.override is None, "empty state")
    aim = _obj_refs(node, "obj_4") if node else []
    yaw_ref = next((i for i, r in enumerate(aim) if "Y Angle" in r), None)
    x_ref = next((i for i, r in enumerate(aim) if "X Offset" in r), None)
    # Links the shipped node already holds into its OWN entity that lead to no
    # part at all: Merlin's aim reads "Potency Rune Node Angle Value", defined
    # nowhere in the game. The game ignores it; the build check refuses it on
    # a copy, which made every Fire and Hit block on Merlin fail to save.
    own = {c.name for c in g.components}
    dangling = [(f.name, i) for f in (EF.fields(node) if node else []) if f.kind == "obj"
                for i, r in enumerate(_obj_refs(node, f.name))
                if r and r.startswith(g.name + "\\")
                and r.rstrip().rstrip('"').rsplit("\\", 1)[-1] not in own]

    def clear_dangling(nd: str) -> None:
        # Inside a number slot a link cannot just go: point it at a plain 0,
        # what the game read through the missing part.
        for fld, i in dangling:
            steps.append({"link": f"{nd}.{fld}[{i}]",
                          "to": num(f"{nd.removeprefix(tag + ' ')} {fld} {i} Zero", 0.0)})
    n_values = sum(len(f.items) for f in EF.fields(spawner) if f.name == "spawner_values") \
        if spawner else 0
    sv_donor = next((c for c in g.components if c.cls == "oCEntityCpntSpawnerValueSettings"
                     and any(f.name == "value" and f.text.startswith("f32")
                             for f in EF.fields(c))), None)
    int_donor = next((c for c in g.components if c.cls == "oCEntityCpntSpawnerValueSettings"
                      and any(f.name == "value" and f.text.startswith("int")
                              for f in EF.fields(c))), None)

    tag = f"Kit {slot.title()}"
    if spec.get("replace") and slot == "trait":
        # Scarlet's trait state plays her transform; cutting its hits alone
        # (_replace) left that in. Taken whole, ended by a timer, unlocked
        # from her talent; the timeline below is all it does.
        steps: list[dict] = _take_button(trigger, slot, g, tag="Kit Trait",
                                         no_cooldown=False)
    else:
        steps = _replace(trigger, g) if spec.get("replace") else []
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
        if not ("fire" in block or "hit" in block or "heal" in block or "summon" in block):
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
            clear_dangling(nd)
            steps += [{"remove_link": f"{sp}.spawner_values[0]"}] * n_values
            for key, (target, default, _, _, scale) in HIT_VALUES.items():
                setv(sp, HIT_ENTITY, key.title(), target,
                     float(block["hit"].get(key, default)) * scale)
            steps.append({"add_link": f"{moments[t]}.activates", "to": sp})
            continue
        if "summon" in block:
            # An enemy as an ally, spawned where a shot would be (one, ahead).
            ent = shot = _summon_for(block["summon"], ctx, slot,
                                     lifetime=block.get("lifetime"), burst=block.get("burst"),
                                     on_hit=bool(block.get("burst_on_hit")),
                                     appear=block.get("appear"), attack=block.get("attack"),
                                     tuning=_attack_tuning_of(block, slot))
            angles, offsets = [0], []
        else:
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
            clear_dangling(nd)
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
            elif "fire" in block and any(block.get(k) is not None
                                         for k in (*PROJ_VALUES, *PROJ_STATUS)):
                # (A summon's own lifetime is its end, not a projectile's.)
                raise KitError(f"kit {slot}: {block['fire']} is not a projectile "
                               "(Projectile_Model); damage, lifetime and effects need one")
            steps.append({"add_link": f"{moments[t]}.activates", "to": sp})
    return steps


def _is_projectile(ent: str) -> bool:
    """Whether ``ent`` inherits Projectile_Model (its generic numbers apply)."""
    return _inherits(ent, b"Projectile_Model\\")


def _is_pet(ent: str) -> bool:
    """Whether ``ent`` already is a pet: Hero_Pet_Model in its parent chain."""
    from . import ally_summon as AS
    from . import entity_check as CK
    from . import entity_components as EC
    todo, seen = [ent], set()
    while todo:
        ref = todo.pop()
        raw = CK._corpus_reader(ref)
        if ref in seen or not raw:
            continue
        seen.add(ref)
        parents = EC.parents(raw)
        if AS.PET_MODEL in parents:
            return True
        todo += parents
    return False


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
        # A slot fired from a named state plays that state's group's clip (a
        # hero locked in its wolf form names its wolf state).
        when = next((c.group for c in g.components if c.name == v.get("when")
                     and c.cls == "oCEntityCpntStateSettings"), None)
        if when:
            groups.insert(0, when)
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
                    "type": kind, "default": default, "own": target is not None})
    return out


def _pet_copy(ent: str, ctx: _Ctx) -> tuple[str, list[dict]]:
    """A shipped pet as the hero's own (``Hero_<id>_Pet<k>``). Piper's rat reads
    13 values of its owner, most of them Piper's own parts (max attacks, damage
    multiplier, alive pets); spawned by another hero those reads found nothing
    and no rat ever appeared. Each read of a part only that hero has reads a
    copy here holding her number; a read of a part every hero has (Hero_Common's
    AP Trait, Character_Common's AP) keeps its link, read from this hero."""
    from . import ally_summon as AS
    from . import entity_check as CK
    from . import entity_components as EC
    raw = CK._corpus_reader(ent)
    if raw is None or EC.parents(raw) != [AS.PET_MODEL]:
        raise KitError(f"kit pets: {ent} must inherit Hero_Pet_Model directly (copy the "
                       "pet itself, not a later version of it)")
    for c in ctx.copies:
        if c.source == ent and c.ref.endswith("_Pet.entity.ot"):
            return c.ref, []
    ref = f"Heroes\\{ctx.folder}\\Hero_{ctx.hid}_Pet.entity.ot"
    steps: list[dict] = []
    parts: dict[str, str | None] = {}
    for r in owner_reads(ent):
        if not r["own"]:
            parts[r["part"]] = None
            continue
        if r["label"] == "Attack Seed Position":
            # Where an attack order sends them: Piper stores her aim there on
            # the trait; here the hero's own position, stored again on every
            # order (_pets). A fixed copy would send them to the world origin.
            parts[r["part"]] = "Kit Pet Centre"
            continue
        part = f"Kit Pet Read {r['label']}"
        donor = _READ_DONORS[r["type"]]
        v = r["default"]
        v = bool(v) if r["type"] == "bool" else int(v) if r["type"] == "int" else v
        steps += [{"clone": [donor], "from": "Projectile_Model/Projectile_Model",
                   "rename": {donor: part}},
                  {"set": f"{part}.value", "value": v}]
        parts[r["part"]] = part
    ctx.copies.append(Copy(ent, ref, parts))
    return ref, steps


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
        if not r.get("own", True) and r["label"] not in overrides:
            # A part every hero has (Character_Common's AP and Level Damage,
            # Hero_Common's AP Trait): read live from this hero, not frozen at
            # the donor's inline 0 (a copied Geppetto dummy hit for nothing).
            parts[r["part"]] = None
            continue
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


#: How `pets` spawn: Sun Wukong's clone spawn (his ultimate's monkeys), whose
#: spread pos picks spots around the hero and runs the spawner per spot, a
#: plain value its count. (Piper's own spawner picks rat or rat king through a
#: selector and has no template to point at another creature.)
_WUKONG_SPAWN = {"Skill Ultimate 1 Special Monkey Spawner": "Kit Pet Spawner",
                 "Skill Ultimate 1 Special Monkey Spread Pos": "Kit Pet Spread Pos",
                 "Skill Ultimate 1 Special Monkey Pathfinding Profile":
                     "Kit Pet Pathfinding Profile",
                 "Special Monkey Random": "Kit Pet Random",
                 "Skill Ultimate 1 Special Monkey Nb": "Kit Pet Count",
                 # The spread's centre: the hero's own position (Character_Common's
                 # Self Entity Listener, which every hero inherits).
                 "Ultimate Ability 1 Direction Store": "Kit Pet Centre"}
_PIPER_ORDERS = {"PET_MASTER_ATTACK_MOVE_ORDER Event Sender": "Kit Pet Attack Order",
                 "PET_MASTER_RECALL_ORDER Event Sender": "Kit Pet Recall Order"}
#: The trait controller's switches a base reads from a condition, as plain
#: values: Scarlet's "Is Trait Ability Active Condition" (true only with her
#: talent "Skill Trait Active") feeds these three; their inline values are the
#: unlocked ones. Piper's whole set was tried first and froze every input after
#: one press: her trait is an aimed command (playtest 2026-11-03).
_TRAIT_UNLOCK = {"value_11": True, "value_12": False, "value_16": False}
_PIPER_HUD = {"HUD Trait Rats Amount": "Kit Pet HUD",
              "HUD Trait Rats Amount Frame": "Kit Pet HUD Frame",
              "HUD Trait Rats Amount Label": "Kit Pet HUD Alive Label",
              "HUD Trait Rats Amount Label_1": "Kit Pet HUD Max Label",
              "Alive Pets Entity Listener": "Kit Pet Alive Listener",
              # The listener's COUNT as a whole number, read live (a label linked
              # to the listener itself reads its position). Not her "Teleporting
              # Pets Count Store": a snapshot she fills only while they teleport,
              # so a label on it stayed at 0.
              "Trait Ability Alive Pets Operation": "Kit Pet Alive Count"}


def _pets(spec, g: EG.EntityGraph, wolf: bool, ctx: _Ctx,
          earlier: list[dict] = ()) -> list[dict]:
    """``pets = { entity = <enemy>, count = 1, button = "trait" }``: pets that
    follow the hero, Piper's way. The enemy is copied onto Hero_Pet_Model
    (follows its master, obeys PET_MASTER_* orders) with its attacks turned on
    enemies; ``count`` of them spawn around the hero when it starts (the select
    screen too, as Piper's rats). ``button``'s ability is replaced by the
    attack order, with no cooldown; leaving combat recalls them (Piper's
    recall: the order is held off while the hero fights).

    With ``talent = "<talent state>"`` it all waits for that talent: picking it
    spawns them, and while it is held the button sends the order on top of its
    own ability, with what the kit's slot block built for that button (a
    summon, a shot) switched off. ``when`` names the button's state, as in a
    slot block (a hero locked in another form)."""
    from . import ally_summon as AS
    if not isinstance(spec, dict) or not spec.get("entity"):
        raise KitError('kit pets = { entity = "<enemy>", count = 1, button = "trait" }')
    unknown = set(spec) - {"entity", "count", "button", "talent", "when", "counter", "appear",
                           "spawn", "burst", "aggro", "lifetime", "burst_on_hit", "attack",
                           "hold", "attack_area", "attack_speed", "attack_debuffs",
                           "attack_cooldown", "attack_reach", "attack_range", "count_talents",
                           "count_card"}
    if unknown:
        raise KitError(f"kit pets has no {', '.join(sorted(unknown))}")
    count = spec.get("count", 1)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 4:
        raise KitError("kit pets count is 1..4 (each one is a creature in co-op)")
    button = spec.get("button", "trait")
    if button not in SLOTS:
        raise KitError(f"kit pets button = {button!r}: one of {', '.join(SLOTS)}")
    counter = spec.get("counter", button)
    if counter != "none" and counter not in SLOTS:
        raise KitError(f"kit pets counter = {counter!r}: \"none\" or one of {', '.join(SLOTS)}")
    # "start": at the start of a run (Piper's); "button": one per press of the
    # button, with its own cooldown (a bomber wolf, playtest 2026-11-04).
    spawn = spec.get("spawn", "start")
    if spawn not in ("start", "button"):
        raise KitError(f"kit pets spawn = {spawn!r}: \"start\" or \"button\"")
    if spawn == "button" and spec.get("talent"):
        raise KitError("kit pets: spawn = \"button\" and a talent do not mix")
    src = _entity_ref(spec["entity"])
    if _is_pet(src):
        # Already a pet (Piper's rat): her logic as shipped, in a copy of the
        # hero's own whose reads of Piper read this hero (see _pet_copy).
        if spec.get("appear"):
            raise KitError("kit pets appear: only an enemy copy has a spawn clip to swap")
        pet, pre = _pet_copy(src, ctx)
    else:
        pre = []
        # A bomber pet: it bursts when it dies, on its first bite too
        # (`burst_on_hit`, Pam's suicide wolves), or when `lifetime` runs out.
        pet = _summon_for(spec["entity"], ctx, "pets", base=AS.PET_MODEL,
                          appear=spec.get("appear"), burst=spec.get("burst"),
                          lifetime=spec.get("lifetime"),
                          on_hit=bool(spec.get("burst_on_hit")), attack=spec.get("attack"),
                          tuning=_attack_tuning_of(spec, "pets"))

    steps: list[dict] = [
        *pre,
        {"clone": list(_WUKONG_SPAWN), "from": "SunWukong", "rename": dict(_WUKONG_SPAWN)},
        {"set": "Kit Pet Spawner.template[1]", "value": pet},
        {"set": "Kit Pet Count.value", "value": count}]
    steps += _pet_count_talents(spec, g)
    talent = spec.get("talent")
    states = {c.name for c in g.components if c.cls == "oCEntityCpntStateSettings"}
    if talent is not None and talent not in states:
        raise KitError(f"kit pets talent = {talent!r} is not a state of this hero "
                       "(a talent's state is its skill controller's, e.g. "
                       "\"Skill Secondary Ignite\")")
    # At the start of a run, or once the talent is picked: the spread pos
    # spawns them. Not in the select screen: the preview copy runs Initialize
    # too, and an enemy body there (no preview behaviour, as Piper's rats
    # have) fell through the floor. Hero_Common's "in a run" tester gates it,
    # as it gates Blood Wolf's wolf lock.
    trigger = _trigger(button, {"when": spec.get("when")}, g, wolf)
    start = trigger if spawn == "button" else talent
    if start is None:
        start = "Kit Pet Spawn"
        empty = next((c for c in g.components
                      if c.cls == "oCEntityCpntStateSettings" and not c.refs
                  and c.override is None), None)
        if empty is None:
            raise KitError("kit pets: this base has no empty state to spawn them from")
        # In a run only (Hero_Common's tester, as the wolf lock uses: it fires
        # at Initialize, outside the select screen's preview), then a timer:
        # at Initialize the hero does not stand in the world yet. A tester
        # tests once, when it is switched on; Piper's "Behaviour Default" gate
        # was still false then and never passed, so nothing ever reached the
        # spawner (probe + Ghidra, 2026-11-03: activation queues the spawner,
        # FUN_14072e460, and SpawnOne was never called for it).
        timer = next((c for c in g.components if c.cls == "oCEntityCpntTimerSettings"
                  and c.override is None), None)
        if timer is None:
            raise KitError("kit pets: this base has no timer to delay the spawn with")
        steps += [{"clone": [empty.name], "rename": {empty.name: start}},
                  {"clone": ["Activate Hero Controller Tester"], "from": "Hero_Common",
                   "rename": {"Activate Hero Controller Tester": "Kit Pet In Run Tester"}},
                  {"clone": [timer.name], "rename": {timer.name: "Kit Pet Start Timer"}},
                  {"set": "Kit Pet Start Timer.duration", "value": 3.0},
                  {"link": "Kit Pet Start Timer.on_tick", "to": ""},
                  {"link": "Kit Pet Start Timer.on_end", "to": start},
                  {"link": "Kit Pet Start Timer.state", "to": ""},
                  # A tester's on_true is a state: one that starts the timer.
                  {"clone": [empty.name], "rename": {empty.name: "Kit Pet Start"}},
                  {"add_link": "Kit Pet Start.activates", "to": "Kit Pet Start Timer"},
                  {"link": "Kit Pet In Run Tester.on_true", "to": "Kit Pet Start"},
                  {"add_link": "Child Event Initialize.activates", "to": "Kit Pet In Run Tester"}]
    steps += [{"add_link": f"{start}.activates", "to": "Kit Pet Centre"},
              {"add_link": f"{start}.activates", "to": "Kit Pet Random"},
              {"add_link": f"{start}.activates", "to": "Kit Pet Spread Pos"}]
    # (The spread runs the spawner once per spot itself; switching the spawner
    # on as well spawned a second pet, playtest 2026-11-03.)

    steps += [{"clone": list(_PIPER_ORDERS), "from": "Piper", "rename": dict(_PIPER_ORDERS)},
              # Piper's orders go to what HER two pet spawners spawned (each
              # sender's targets = Spawned Entity Collectors naming them); left
              # so, every press reached nobody (corpus, 2026-11-03).
              {"retarget_targets": "Kit Pet Attack Order.targets", "to": "Kit Pet Spawner"},
              {"retarget_targets": "Kit Pet Recall Order.targets", "to": "Kit Pet Spawner"},
              # Where the order sends them (a copied pet reads it): stored first.
              {"add_link": f"{trigger}.activates", "to": "Kit Pet Centre"},
              {"add_link": f"{trigger}.activates", "to": "Kit Pet Attack Order"}]
    if talent is not None:
        # The button keeps its ability (and its own end); the talent holds off
        # what the slot block added to it. Without the talent the order goes
        # to no pet, which does nothing.
        built = [s["to"] for s in earlier if s.get("add_link") == f"{trigger}.activates"]
        steps += [{"add_link": f"{talent}.disables_while_active?", "to": b} for b in built]
    else:
        # `hold`: how long the button's state lasts (what it holds while
        # active runs that long: a howl's upper/lower body split).
        hold = spec.get("hold", 0.2)
        if isinstance(hold, bool) or not isinstance(hold, (int, float)) or hold <= 0:
            raise KitError(f"kit pets hold is seconds, got {hold!r}")
        steps += _take_button(trigger, button, g, earlier, no_cooldown=spawn != "button",
                              hold=float(hold))
    combat, recall = _recall(g)
    steps += recall
    if spec.get("aggro"):
        # Into the fight on its own: entering combat (the hero's "is in
        # combat", whose hold is also what lets Piper's recall wait for a
        # fight's end) sends the attack order around the hero, as a press of
        # the button does. The pet's own wider detection (_summon_end) does
        # the rest, as Piper's rats engage while following.
        steps += [{"add_link": f"{combat}.activates", "to": "Kit Pet Centre"},
                  {"add_link": f"{combat}.activates", "to": "Kit Pet Attack Order"}]
        # And again every 1.5 s while the fight lasts: one order at its start
        # left a pet spawned later, or done with its target, following and
        # never fighting again (playtest 2026-11-04).
        tmr = next((c for c in g.components if c.cls == "oCEntityCpntTimerSettings"
                    and c.override is None), None)
        empty = next((c for c in g.components if c.cls == "oCEntityCpntStateSettings"
                      and not c.refs and c.override is None), None)
        if tmr is None or empty is None:
            raise KitError("kit pets aggro: this base has no timer or empty state to repeat with")
        steps += [{"clone": [empty.name], "rename": {empty.name: "Kit Pet Aggro"}},
                  {"add_link": "Kit Pet Aggro.activates", "to": "Kit Pet Centre"},
                  {"add_link": "Kit Pet Aggro.activates", "to": "Kit Pet Attack Order"},
                  {"clone": [tmr.name], "rename": {tmr.name: "Kit Pet Aggro Timer"}},
                  {"set": "Kit Pet Aggro Timer.duration", "value": 1.5},
                  {"set": "Kit Pet Aggro Timer.count", "value": 100000},
                  {"link": "Kit Pet Aggro Timer.on_tick", "to": "Kit Pet Aggro"},
                  {"link": "Kit Pet Aggro Timer.on_end", "to": ""},
                  {"link": "Kit Pet Aggro Timer.state", "to": ""},
                  {"add_link": f"{combat}.while_active", "to": "Kit Pet Aggro Timer"}]
    if counter != "none":
        steps += _counter(g, start)
        # Count again on every order too (one may have died since).
        steps.append({"add_link": f"{trigger}.activates", "to": "Kit Pet Recount"})
        # Over that button's icon (Piper's sits on her trait).
        word = SLOTS[counter][0].removesuffix(" 1").removesuffix(" 2")
        steps.append({"set": "Kit Pet HUD.obj_6[0]", "value": f"{word}_Layout_Top"})
    return steps


def _take_button(trigger: str, button: str, g: EG.EntityGraph,
                 earlier: list[dict] = (), *, tag: str = "Kit Pet Order",
                 no_cooldown: bool = True, hold: float = 0.2) -> list[dict]:
    """The button's own ability out, for what the kit puts on it (the pet
    order, or a slot block's timeline on the trait). Each link goes by name,
    past any a slot block already cut (``earlier``): by index, the extra
    removals took the order with them. ``no_cooldown``: the pet order's, as
    Piper's; a summon keeps the base's (Scarlet's charge-based trait at 0
    never came back after one press, playtest 2026-11-03)."""
    steps: list[dict] = []
    t = next(c for c in g.components if c.name == trigger)
    for f in EF.fields(t):
        if f.kind == "ref[]":
            gone = {s.get("to") for s in earlier
                    if s.get("remove_link") == f"{trigger}.{f.name}"}
            for it in f.items:
                name = it.text.rstrip().rsplit("\\", 1)[-1].removesuffix('""')
                if name not in gone:
                    steps.append({"remove_link": f"{trigger}.{f.name}", "to": name})
    # The cleared lists held what ENDED the state (Scarlet: the transform clip,
    # whose end event deactivates it; Piper: her trait clip). A state that never
    # ends keeps its ability in use, so the button stayed locked after the
    # first press. A short timer ends it instead.
    timer = next((c for c in g.components if c.cls == "oCEntityCpntTimerSettings"
                  and c.override is None), None)
    empty = next((c for c in g.components
                  if c.cls == "oCEntityCpntStateSettings" and not c.refs
                  and c.override is None), None)
    if timer is None or empty is None:
        raise KitError(f"kit pets: this base has no timer or empty state to end the "
                       f"{button} order with")
    end, tm = f"{tag} End", f"{tag} Timer"
    steps += [{"clone": [empty.name], "rename": {empty.name: end}},
              {"add_link": f"{end}.deactivates?", "to": trigger},
              {"clone": [timer.name], "rename": {timer.name: tm}},
              {"set": f"{tm}.duration", "value": hold},
              {"link": f"{tm}.on_tick", "to": ""},
              {"link": f"{tm}.on_end", "to": end},
              {"link": f"{tm}.state", "to": ""},
              {"add_link": f"{trigger}.activates", "to": tm}]
    ctrl = next((c for c in g.components if c.cls == "oCDtEntityCpntAbilityControllerSettings"
                 and any(r.path.rstrip().endswith("\\" + trigger) for r in c.refs)), None)
    if ctrl is not None:
        if no_cooldown:
            steps.append({"set": f"{ctrl.name}.value_4", "value": 0.0})
        if button == "trait":
            # Usable without a talent. Scarlet's reads "Is Trait Ability Active
            # Condition" into three of these: true only while her talent "Skill
            # Trait Active" is held (manual transforming is a talent of hers),
            # so without it the trait stayed locked (corpus, 2026-11-03).
            for fld, v in _TRAIT_UNLOCK.items():
                steps.append({"set": f"{ctrl.name}.{fld}", "value": v})
    return steps


def _recall(g: EG.EntityGraph) -> tuple[str, list[dict]]:
    """The hero's "in combat" state and the steps that recall the pets once a
    fight ends."""
    steps: list[dict] = []
    # Recall once a fight ends: Piper's "is in combat" holds the order off.
    # Heroes override it already (Scarlet and Piper as "Child State Is In
    # Combat"); a hero that does not gets its own override.
    combat = next((c.name for c in g.components if c.override is not None
                   and c.override.path.rstrip().endswith("\\Child State Can Fight")), None)
    if combat is None:
        combat = "Child State Can Fight"
        steps.append({"override": combat, "from": "Character_Common/Character_Common"})
    steps.append({"add_link": f"{combat}.disables_while_active?", "to": "Kit Pet Recall Order"})
    return combat, steps


#: A count a talent raises, the game's way: Geppetto's "Max Controllable
#: Dummies" selector (4 while his Extra Charge talent is held, else 3) and
#: Piper's "More Controllable Pets" count (her talent's amount + the default;
#: operation 0 = add).
_TALENT_COUNT = ("Geppetto", "Trait Ability Max Controllable Dummies Selector")
_COUNT_ADD = ("Piper", "Skill Trait More Controllable Pets Count Operation")


def _pet_count_talents(spec: dict, g: EG.EntityGraph) -> list[dict]:
    """``count_talents = { "<talent state>" = n }``: while a talent's state is
    held, each press calls ``n`` more pets (they stack). ``count_card =
    "<String Format>"``: that card's ``{0}`` shows the count as it stands.

    "Kit Pet Count Total" is what the spread and the HUD read: the base count
    alone, or a chain of adds, one per talent, of a selector giving ``n``
    while its talent is held and 0 otherwise."""
    talents = spec.get("count_talents") or {}
    if not isinstance(talents, dict):
        raise KitError('kit pets count_talents = { "<talent state>" = <pets it adds> }')
    states = {c.name for c in g.components if c.cls == "oCEntityCpntStateSettings"}
    steps: list[dict] = []
    total = "Kit Pet Count"
    sel_src, sel = _TALENT_COUNT
    add_src, add = _COUNT_ADD
    for k, (state, n) in enumerate(talents.items(), 1):
        if state not in states:
            raise KitError(f"kit pets count_talents: the hero has no state {state!r}")
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 4:
            raise KitError(f"kit pets count_talents: {state!r} adds 1..4 pets, got {n!r}")
        s_k, o_k = f"Kit Pet Talent Count {k}", f"Kit Pet Count Add {k}"
        steps += [{"clone": [sel], "from": sel_src, "rename": {sel: s_k}},
                  {"link": f"{s_k}.entries[0][0]", "to": state},
                  {"set": f"{s_k}.entries[0][1]", "value": n},
                  {"set": f"{s_k}.entries[1][1]", "value": 0},
                  {"clone": [add], "from": add_src, "rename": {add: o_k}},
                  {"link": f"{o_k}.a", "to": s_k},
                  {"link": f"{o_k}.b", "to": total}]
        total = o_k
    # One name for whatever the count is now (a talent-less total is the base).
    steps += [{"clone": ["Kit Pet Count"], "rename": {"Kit Pet Count": "Kit Pet Zero Count"}},
              {"set": "Kit Pet Zero Count.value", "value": 0},
              {"clone": [add], "from": add_src, "rename": {add: "Kit Pet Count Total"}},
              {"link": "Kit Pet Count Total.a", "to": total},
              {"link": "Kit Pet Count Total.b", "to": "Kit Pet Zero Count"},
              {"link": "Kit Pet Spread Pos.value_2", "to": "Kit Pet Count Total"}]
    card = spec.get("count_card")
    if card is not None:
        part, _, slot = str(card).partition("[")
        n = int(slot.rstrip("]")) if slot else 0
        fmt = next((c for c in g.components if c.name == part), None)
        if fmt is None or fmt.cls != "oCEntityCpntStringFormatValueSettings":
            raise KitError(f"kit pets count_card: {part!r} is not one of the hero's String "
                           "Formats (a card's text and its {N} numbers)")
        steps.append({"link": f"{part}.obj_4[{n}]", "to": "Kit Pet Count Total"})
    return steps


def _counter(g: EG.EntityGraph, start: str) -> list[dict]:
    steps: list[dict] = []
    # The counter over the trait icon, Piper's "alive / max": her HUD panel,
    # frame and two labels, the alive one reading a copy of her pet listener
    # (an inline filter, no link into her own parts), the max one the count.
    steps += [{"clone": list(_PIPER_HUD), "from": "Piper", "rename": dict(_PIPER_HUD)},
              {"link": "Kit Pet HUD Alive Label.value_23", "to": "Kit Pet Alive Count"},
              {"link": "Kit Pet HUD Max Label.value_23", "to": "Kit Pet Count Total"},
              {"add_link": f"{start}.activates", "to": "Kit Pet Alive Listener"}]
    # The listener counts when it is switched on, and the pets come a few
    # frames after the spawn starts: Piper switches hers off and on again
    # after every spawn. So does this, 0.5 s after the start.
    timer = next((c for c in g.components if c.cls == "oCEntityCpntTimerSettings"
                  and c.override is None), None)
    empty = next((c for c in g.components
                  if c.cls == "oCEntityCpntStateSettings" and not c.refs
                  and c.override is None), None)
    if timer is None or empty is None:
        raise KitError("kit pets: this base has no timer or empty state to count them with")
    steps += [{"clone": [empty.name], "rename": {empty.name: "Kit Pet Recount"}},
              {"add_link": "Kit Pet Recount.deactivates?", "to": "Kit Pet Alive Listener"},
              {"add_link": "Kit Pet Recount.activates", "to": "Kit Pet Alive Listener"},
              {"clone": [timer.name], "rename": {timer.name: "Kit Pet Recount Timer"}},
              {"set": "Kit Pet Recount Timer.duration", "value": 0.5},
              {"link": "Kit Pet Recount Timer.on_tick", "to": ""},
              {"link": "Kit Pet Recount Timer.on_end", "to": "Kit Pet Recount"},
              {"link": "Kit Pet Recount Timer.state", "to": ""},
              {"add_link": f"{start}.activates", "to": "Kit Pet Recount Timer"}]
    return steps


def _summon_for(enemy, ctx: _Ctx, slot: str, base: str | None = None, *,
                lifetime=None, burst=None, on_hit: bool = False, appear=None,
                attack=None, tuning: tuple = _NO_TUNING) -> str:
    """The ref to spawn for ``summon = <enemy>``: an ally copy of it in the
    hero's folder (its model layer and the variant, see ally_summon.build).
    One copy per enemy and end, however many blocks summon it.

    ``lifetime`` (seconds): it dies on its own then, as Sun Wukong's clone.
    ``burst`` (an entity): spawned where it dies, however it dies (killed or
    run out), e.g. the hero's bleed bomb. ``on_hit``: its first attack ends it
    there (a suicide wolf: it bursts on the enemy, not where its time ran out).
    ``appear`` (one of the enemy's clips): played as it appears instead of its
    own spawn clip (a wolf's climbs out of the ground). It must END: its end is
    what finishes the spawn (Character_Common's appearance clip ends the
    state), so a looping clip would keep it there."""
    from . import ally_summon as AS
    if lifetime is not None and (isinstance(lifetime, bool)
                                 or not isinstance(lifetime, (int, float)) or lifetime <= 0):
        raise KitError(f"kit {slot}: lifetime is a number of seconds, got {lifetime!r}")
    if burst is not None and not (isinstance(burst, str) and burst):
        raise KitError(f"kit {slot}: burst is an entity path, got {burst!r}")
    src = _entity_ref(enemy)
    if on_hit and not burst:
        raise KitError(f"kit {slot}: burst_on_hit needs a burst to spawn")
    if tuning != _NO_TUNING and not attack:
        raise KitError(f"kit {slot}: attack_area/reach/speed/debuffs/cooldown tune the attack "
                       "named by `attack`; name one")
    end = (lifetime, _entity_ref(burst) if burst else None, on_hit, appear, attack, tuning)
    for c in ctx.copies:
        if (c.data is not None and c.source == src and c.base == (base or None)
                and c.end == end):
            return c.ref
    k = len({c.ref.removesuffix(".entity.ot").removesuffix("_Model")
             for c in ctx.copies}) + 1
    stem = f"Heroes\\{ctx.folder}\\Hero_{ctx.hid}_Summon{k}"
    variant_ref, model_ref = stem + ".entity.ot", stem + "_Model.entity.ot"
    try:
        out = AS.build(src, model_ref, variant_ref, f"{ctx.hid}:summon:{src}:{end}",
                       base=base or AS.ALLY_MODEL)
    except AS.SummonError as e:
        raise KitError(f"kit {slot}: summon {enemy}: {e}") from None
    out = _summon_end(out, model_ref, variant_ref, lifetime, end[1], slot,
                      pet=base == AS.PET_MODEL, on_hit=on_hit)
    if appear:
        out = _appear(out, model_ref, str(appear), slot)
    if attack:
        out = _attack(out, model_ref, variant_ref, str(attack), slot)
        out = _tune_attack(out, model_ref, str(attack), tuning, slot)
        if tuning[5] is not None:
            out = _attack_range(out, model_ref, variant_ref, tuning[5], slot)
    from . import entity_components as EC
    model_src = next(p for p in EC.parents(AS._read(src)) if p != AS.ENEMY_MODEL)
    reads = {"Kit Owner Seed Position": "Kit Pet Centre"} if base == AS.PET_MODEL else {}
    ctx.copies.append(Copy(model_src, model_ref, reads, out[model_ref], base, end))
    ctx.copies.append(Copy(src, variant_ref, {}, out[variant_ref], base, end))
    return variant_ref


def _pet_speed(out: dict[str, bytes], model_ref: str, variant_ref: str) -> list[dict]:
    """A pet keeps up with its master: Hero_Pet_Model's "Move Locomotion
    Speed" reads the owner's run speed. An enemy's own override of that part
    (a dire wolf's fixed 4 and 4.6, lower in the chain) replaced it, so the
    copy trailed behind; each such override reads the owner again instead."""
    from . import ally_summon as AS
    from . import entity_check as CK
    pet_model = AS.PET_MODEL.replace("\\", "/").removesuffix(".entity.ot")
    pet = EG.parse(CK._corpus_reader(AS.PET_MODEL)).components
    speed = next(c.override.guid for c in pet if c.name == "Move Locomotion Speed")
    read = "Owner Move Locomotion Max Speed Get Value"
    steps: list[dict] = []
    for k, ref in enumerate((model_ref, variant_ref)):
        stem = ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
        for c in EG.parse(out[ref]).components:
            if c.override is not None and c.override.guid == speed:
                mine = f"Kit Owner Run Speed {k + 1}"
                steps += [{"clone": [read], "from": pet_model, "rename": {read: mine},
                           "entity": stem},
                          {"link": f"{c.name}.value", "to": mine, "entity": stem}]
    # Steering as Piper's rats: re-path every 0.1 s (NPC_Common: 0.5) and turn
    # at 10 pi rad/s (a wolf: 4 pi), or it swings wide and trails its master.
    # A wolf's night run speed (a fixed 6) reads the owner's too.
    m_stem = model_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    names = {c.name for c in EG.parse(out[model_ref]).components}
    npc = "Enemies/NPC_Common/NPC_Common"
    for part, value in (("Move Steering Path Update Period", 0.1),
                        ("Move Locomotion Look At Max Rotation Speed Value", 31.4159)):
        if part not in names:
            steps.append({"override": part, "from": npc, "entity": m_stem})
        steps.append({"set": f"{part}.value", "value": value, "entity": m_stem})
    # A wolf's night and strafe speeds (fixed 6 and 2: it circles its target
    # at a walk) read the owner's too, or it trailed behind (playtest).
    for k, extra in enumerate(("Move Night Locomotion Max Speed",
                               "Move Strafe Locomotion Max Speed")):
        if extra in names:
            mine = f"Kit Owner Run Speed Extra {k + 1}"
            steps += [{"clone": [read], "from": pet_model, "rename": {read: mine},
                       "entity": m_stem},
                      {"link": f"{extra}.value", "to": mine, "entity": m_stem}]
    return steps


def _attack(out: dict[str, bytes], model_ref: str, variant_ref: str, attack: str,
            slot: str) -> dict[str, bytes]:
    """The enemy fights with its ``attack`` (``"Bite"``): the variant's fighting
    selector picks its attack by an entry (a state and its condition, the
    dire wolf's "Attack Double Slash", its claw); that entry now names
    "State Attack <attack>" and "Attack <attack> Condition" of the model."""
    from .entity_graph_edit import EntityFile, kind_label
    model = EG.parse(out[model_ref])
    by = {c.name: c for c in model.components}
    m_stem = model_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    state, cond = by.get(f"State Attack {attack}"), by.get(f"Attack {attack} Condition")
    if state is None or cond is None:
        have = sorted(c.name[len("State Attack "):] for c in model.components
                      if c.name.startswith("State Attack "))
        raise KitError(f"kit {slot}: attack {attack!r}: this enemy's attacks are "
                       f"{', '.join(have)}")
    v_stem = variant_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    ef = EntityFile(out[variant_ref], v_stem)
    sel = next((c for c in ef.graph().components if c.name == "Bhv Fighting State Selector"),
               None)
    if sel is None:
        raise KitError(f"kit {slot}: attack: this enemy has no fighting selector of its own")
    old = next((r for r in sel.refs if r.path.rstrip().startswith("[State]")
                and "\\State Attack " in r.path), None)
    if old is None:
        raise KitError(f"kit {slot}: attack: its fighting selector names no attack")
    old_name = old.path.rstrip().rstrip('"').rsplit("State Attack ", 1)[-1]
    old_cond = next((r for r in sel.refs
                     if r.path.rstrip().rstrip('"').endswith(f"Attack {old_name} Condition")), None)
    for o, new in ((old, state), (old_cond, cond)):
        if o is None or o.guid == new.guid:
            continue
        label = (f"[{kind_label(new.cls)}] {m_stem}\\" + (f"{new.group}\\" if new.group else "")
                 + new.name)
        ef.retarget_external(sel.name, o.guid, new.guid, label)
    return {**out, variant_ref: ef.to_bytes()}


def _attack_tuning_of(block: dict, slot: str) -> tuple:
    """``(area, speed, debuffs, cooldown, reach)`` of a summon block:
    ``attack_area`` (x the width of its hit cone), ``attack_reach`` (x the
    radius its hit shape reads), ``attack_speed`` (x its clips' play speed),
    ``attack_debuffs = false`` (its hit applies none of its statuses),
    ``attack_cooldown`` (seconds before it tries that attack again)."""
    out = []
    for key, hi in (("attack_area", 10.0), ("attack_speed", 5.0)):
        v = block.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                              or not 0 < v <= hi):
            raise KitError(f"kit {slot}: {key} is a multiplier above 0, up to {hi:g}; got {v!r}")
        out.append(None if v is None else float(v))
    d = block.get("attack_debuffs", True)
    if not isinstance(d, bool):
        raise KitError(f"kit {slot}: attack_debuffs is true or false, got {d!r}")
    cd = block.get("attack_cooldown")
    if cd is not None and (isinstance(cd, bool) or not isinstance(cd, (int, float))
                           or not 0 < cd <= 60):
        raise KitError(f"kit {slot}: attack_cooldown is seconds above 0, up to 60; got {cd!r}")
    reach = block.get("attack_reach")
    if reach is not None and (isinstance(reach, bool) or not isinstance(reach, (int, float))
                              or not 0 < reach <= 10):
        raise KitError(f"kit {slot}: attack_reach is a multiplier above 0, up to 10; got {reach!r}")
    rng = block.get("attack_range")
    if rng is not None and (isinstance(rng, bool) or not isinstance(rng, (int, float))
                            or not 0.5 <= rng <= 20):
        raise KitError(f"kit {slot}: attack_range is metres, 0.5 to 20; got {rng!r}")
    return (*out, d, None if cd is None else float(cd), None if reach is None else float(reach),
            None if rng is None else float(rng))


def _cone_angle(p: bytearray, names: list[str]) -> int:
    """Offset of the f32 cone angle (full width, radians) in an in-cone
    traverser's payload: its LAST number slot, a literal (the wolf's Bite:
    0.5236, pi/6; shipped literals run 0.44 .. 2 pi). Fails
    closed (-1) on anything else."""
    from .entity_graph_edit import _B
    vp = _B + struct.pack("<I", names.index("oCEntityCpntValuePicker"))
    un = _B + struct.pack("<I", names.index("oCEntityValueUnion"))
    a = p.rfind(vp)
    u = p.find(un, a) if a >= 0 else -1
    if a < 0 or u < 0 or p[a + 8] != 0 or struct.unpack_from("<I", p, u + 8)[0] != 0:
        return -1
    v = struct.unpack_from("<f", p, u + 16)[0]
    return u + 16 if 0 < v <= 2 * math.pi else -1


def _tune_attack(out: dict[str, bytes], model_ref: str, attack: str, tuning: tuple,
                 slot: str) -> dict[str, bytes]:
    """Enemy attacks are timed against heroes standing still; on our side the
    target moves (Pam, 2026-11-05). On the copy's "Attack <attack>" group:

    * area: the attack's HIT shape (Gpn Target Attack -> its computer -> its
      traverser) covers ``area`` x the ground. A cone grows its ANGLE (its full
      width in radians, the Bite's pi/6 = 30 deg; shipped cones run up to 2 pi),
      capped at 2 pi. Any other shape grows its "...Radius" values by
      sqrt(area).
    * reach: those "...Radius" values times ``reach`` (a cone's too). The
      Bite's cone starts 2.5 m BEHIND the wolf, so its 4.6 m ends ~2 m ahead:
      enough for a hero it lunged at, short of a big enemy. x2 made it land
      (Pam's playtest); x4 reached behind the target; only widening the cone
      (reach x1) landed nothing at all.
    Neither moves the distance the enemy decides to attack from (NPC_Common's
    Fighting Seek Attack Distances).
    * speed: each animatic's play speed (value_9, the field a hero's
      Basic Attack Speed drives; its timeline's events scale with it).
    * debuffs off: each of the attack's damage debuffs gets its "is it on"
      slot (its first number) as a literal false. Removing the entry instead
      would orphan its sub-object; the list keeps its shape.
    * cooldown: "Attack <attack> Cooldown" lasts that long (every entry of the
      selector it reads), and the wait between ANY two attacks is no longer.
      A bite at something that cannot be hit yet (a treant rising from the
      ground) lands nothing; it tries again soon instead (Pam)."""
    area, speed, debuffs, cooldown, reach, _range = tuning
    if tuning == _NO_TUNING:
        return out
    from .entity_graph_edit import EntityEditError, EntityFile
    m_stem = model_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    ef = EntityFile(out[model_ref], m_stem)
    group = f"Attack {attack}"
    comps = [c for c in ef.graph().components if c.group == group]
    # Stripped: shipped names can end in a space ("... Best One Computer ").
    by = {c.name.strip(): c for c in ef.graph().components}
    names = [x.name for x in ef.cf.classes]

    def ref_name(c, fld: str) -> str | None:
        f = next((x for x in EF.fields(c) if x.name == fld), None)
        t = (f.text if f else "").split(" <- ")[-1].strip() if f and "<-" in f.text else ""
        return t.rsplit("\\", 1)[-1].strip() if t else None

    if area is not None or reach is not None:
        # Radius name -> factor: a cone's grows by reach only (its angle takes
        # the area); any other shape's by reach x sqrt(area).
        grow: dict[str, float] = {}
        cones = 0
        for ta in (c for c in comps if c.cls == "oCEntityCpntGpnTargetAttackSettings"):
            comp = by.get(ref_name(ta, "ref_2") or "")
            trav = by.get(ref_name(comp, "ref_3") or "") if comp else None
            if trav is None:
                continue
            for x in ef.subtree({trav.index - 1}):
                cone = ef._class(x) == "oCEntityGpnInConeTraverserSettings"
                if cone and area is not None:
                    at = _cone_angle(ef.objects[x], names)
                    if at < 0:
                        raise KitError(f"kit {slot}: attack_area: {attack}'s cone has no "
                                       "literal angle to widen")
                    v = struct.unpack_from("<f", ef.objects[x], at)[0]
                    struct.pack_into("<f", ef.objects[x], at, min(v * area, 2 * math.pi))
                    cones += 1
                factor = (reach or 1.0) * (1.0 if cone else math.sqrt(area or 1.0))
                for m in re.finditer(rb'\[Value\] [^"\x00]*?\\([^\\"\x00]+)""', ef.objects[x]):
                    n = m.group(1).decode().strip()
                    if "Radius" in n and n in by and factor != 1.0:
                        grow[n] = factor
        if (not cones and not grow) or (reach not in (None, 1.0) and not grow):
            raise KitError(f"kit {slot}: attack_area/reach: {attack}'s hit shape has no "
                           "angle or radius to grow")
        for n, factor in sorted(grow.items()):
            v = next(f for f in EF.fields(by[n]) if f.name == "value")
            if "<-" in v.text:
                raise KitError(f"kit {slot}: attack_area/reach: {n} is read from elsewhere")
            ef.set_value(by[n].name, "value", float(v.text.split()[-1]) * factor)
    if cooldown is not None:
        tm = by.get(f"Attack {attack} Cooldown")
        if tm is None or tm.cls != "oCEntityCpntTimerSettings":
            raise KitError(f"kit {slot}: attack_cooldown: {attack} has no cooldown timer")
        d = next(f for f in EF.fields(tm) if f.name == "duration")
        sel = by.get(ref_name(tm, "duration") or "") if "<-" in d.text else None
        if sel is not None and sel.cls == "oCEntityCpntValueSelectorSettings":
            entries = next(f for f in EF.fields(sel) if f.name == "entries")
            for i in range(len(entries.items)):
                ef.set_value(sel.name, f"entries[{i}][1]", cooldown)
        elif "<-" in d.text:
            raise KitError(f"kit {slot}: attack_cooldown: its timer reads {d.text!r}")
        ef.set_value(tm.name, "duration", cooldown)
        for c in ef.graph().components:
            if c.cls == "oCEntityCpntTimerSettings" and c.group == "Bhv Fighting" \
                    and c.name.endswith("All Attack Cooldown"):
                now = float(next(f for f in EF.fields(c) if f.name == "duration").text.split()[1])
                ef.set_value(c.name, "duration", min(now, cooldown))
    if speed is not None:
        anims = 0
        for c in comps:
            if c.cls != "oCEntityCpntAnimaticSettings":
                continue
            f = next((x for x in EF.fields(c) if x.name == "value_9"), None)
            if f is None or "<-" in f.text:
                continue
            ef.set_value(c.name, "value_9", float(f.text.split()[-1]) * speed)
            anims += 1
        if not anims:
            raise KitError(f"kit {slot}: attack_speed: {attack} has no clip of its own")
    if not debuffs:
        n_off = 0
        for c in comps:
            if c.cls != "oCDtEntityCpntDamageSettings":
                continue
            f = next((x for x in EF.fields(c) if x.name == "bytes_36"), None)
            if f is None:
                continue
            for k in range(struct.unpack_from("<I", c.body, f.offset)[0]):
                try:
                    ef.switch_off_subobject(c.name, "bytes_36", k)
                except EntityEditError as e:
                    raise KitError(f"kit {slot}: attack_debuffs: {e}") from None
                n_off += 1
        if not n_off:
            raise KitError(f"kit {slot}: attack_debuffs: {attack} applies no debuff")
    return {**out, model_ref: ef.to_bytes()}


def _attack_range(out: dict[str, bytes], model_ref: str, variant_ref: str, rng: float,
                  slot: str) -> dict[str, bytes]:
    """How close the summon gets before it attacks: NPC_Common's "Fighting Seek
    Max Attack Distance" (it attacks from within it) and "... Best ..." (where it
    tries to stand), on whichever file of the copy sets them (a dire wolf's
    variant: 4.5 and 3). An enemy commits from 4.5 m against a hero standing
    still; a moving enemy left the bite's cone during its wind-up, so the bite
    looked short (Pam's playtest 2026-11-05). This is not the bite's reach
    (``attack_reach``): it is where the summon decides to start it."""
    from .entity_graph_edit import EntityFile
    names = ("Fighting Seek Max Attack Distance", "Fighting Seek Best Attack Distance")
    done: set[str] = set()
    new = dict(out)
    for ref in (variant_ref, model_ref):
        stem = ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
        ef = EntityFile(new[ref], stem)
        have = {c.name for c in ef.graph().components}
        for n in names:
            if n in have and n not in done:
                v = rng if "Max" in n else rng * 2 / 3
                ef.set_value(n, "value", v)
                done.add(n)
        new[ref] = ef.to_bytes()
    if "Fighting Seek Max Attack Distance" not in done:
        raise KitError(f"kit {slot}: attack_range: the summon sets no attack distance of its own")
    return new


#: The wind-up glow every enemy attack plays (the wolf's Bite, Double Slash and
#: Giant Leap all do): a warning to the HERO it is aimed at. On a summon's
#: side it only warns the player about their own ally (Pam, 2026-11-05).
_WARNING_VFX = b"Settings\\FX\\Common_FX\\Unstoppable_Glow.vfx.ot"


def _no_warnings(model: bytes, m_stem: str) -> list[dict]:
    """Steps that silence every warning-glow Fx of a summon copy: the
    animatic timeline blocs that start one start an inert timer instead (no
    shipped bloc points at nothing, so a blank one is not risked), and state
    lists drop it."""
    from .entity_graph_edit import _B, EntityEditError, EntityFile
    ef = EntityFile(model, m_stem)
    g = ef.graph()
    warn = {}
    for c in g.components:
        if c.cls != "oCEntityCpntFxSettings":
            continue
        f = next((x for x in EF.fields(c) if x.name == "bytes_1"), None)
        if f is None:
            continue
        cnt = struct.unpack_from("<I", c.body, f.offset)[0]
        ids = struct.unpack_from(f"<{cnt}I", c.body, f.offset + 4)
        if any(_WARNING_VFX in ef.objects[i] for i in ids):
            warn[c.guid] = c.name
    if not warn:
        return []
    picker = _B + struct.pack("<I", [x.name for x in ef.cf.classes].index("oCEntityCpntPicker"))
    blocs: list[dict] = []
    for c in g.components:
        if c.cls != "oCEntityCpntAnimaticSettings":
            continue
        i = 0
        while True:
            try:
                _c, sub = ef._cinebloc(c.name, i)
            except EntityEditError:
                break
            p = ef.objects[sub]
            at = p.find(picker)
            if at >= 0 and bytes(p[at + 8:at + 24]) in warn:
                blocs.append({"link": f"{c.name}.cinebloc[{i}]", "to": "Kit No Warning"})
            i += 1
    lists = [{"remove_link": f"{c.name}.{f.name}", "to": warn[r.guid]}
             for c in g.components for f in EF.fields(c) if f.kind == "ref[]"
             for r in c.refs if r.guid in warn and warn[r.guid] in f.text]
    if not blocs:
        return lists
    src, timer = _LIFE_TIMER
    return [{"clone": [timer], "from": src, "rename": {timer: "Kit No Warning"}},
            {"set": "Kit No Warning.duration", "value": 0.05},
            {"link": "Kit No Warning.on_end", "to": ""},
            {"link": "Kit No Warning.on_tick", "to": ""},
            {"link": "Kit No Warning.state", "to": ""},
            *blocs, *lists]


def _appear(out: dict[str, bytes], model_ref: str, clip: str, slot: str) -> dict[str, bytes]:
    """The copy's "Spawning Default Appearance Anim" playing ``clip``."""
    from . import entity_strings as ES
    model = out[model_ref]
    anim = next((c for c in EG.parse(model).components
                 if c.name == "Spawning Default Appearance Anim"), None)
    if anim is None:
        raise KitError(f"kit {slot}: appear: this enemy has no spawn clip of its own")
    old = re.search(rb"Characters\\[^\x00\"]+?\.fbx", anim.body)
    have = set(re.findall(rb"Characters\\[^\x00\"]+?\.fbx", model))
    want = clip.replace("/", "\\").encode()
    if want not in have:
        raise KitError(f"kit {slot}: appear {clip!r} is not one of this enemy's clips")
    if re.search(rb"_Loop\.fbx$", want):
        raise KitError(f"kit {slot}: appear {clip!r} loops; its end finishes the spawn")
    blob = ES.replace_strings(model, {old.group(0).decode(): want.decode()},
                              require_all=False)
    return {**out, model_ref: blob}


#: Where a summon's burst spawns: Beowulf's shockwave spawner drops its entity
#: where he stands, unattached (no position source).
_BURST_SPAWNER = ("Beowulf", "Primary Ability Effect Spawner")
#: How Sun Wukong's clone ends its life: a timer that sends it into dying.
_LIFE_TIMER = ("Heroes/Hero_SunWukong/Hero_SunWukong_Ultimate_1_AI_Clone", "Life Timer")


def _summon_end(out: dict[str, bytes], model_ref: str, variant_ref: str, lifetime,
                burst: str | None, slot: str, pet: bool = False,
                on_hit: bool = False) -> dict[str, bytes]:
    """The summon's own end, built on its model copy: Character_Common's
    "Child Behaviour Dying" (entered however it dies) spawns ``burst`` where it
    stands; a life timer sends it into "Behaviour Dying" after ``lifetime`` s.
    Neither Ally_Model nor NPC_Common overrides the two states they use.

    A ``pet`` is also tagged as Piper's rats are ("Alive Additional Flags
    Value" = Rat_Pet): the alive count over the button (a copy of her pet
    listener) collects exactly that tag. A Piper in the same game counts
    them too."""
    from . import ability_edit as AE
    from . import ally_summon as AS
    from . import entity_check as CK
    common = "Character_Common/Character_Common"
    m_stem = model_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    v_stem = variant_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    steps: list[dict] = []
    if burst:
        donor_hero, donor = _BURST_SPAWNER
        raw = CK._corpus_reader(f"Heroes\\Hero_{donor_hero}\\Hero_{donor_hero}.entity.ot")
        d = next(c for c in EG.parse(raw).components if c.name == donor)
        n_values = sum(len(f.items) for f in EF.fields(d) if f.name == "spawner_values")
        steps += [{"clone": [donor], "from": donor_hero, "rename": {donor: "Kit Burst Spawner"}},
                  {"set": "Kit Burst Spawner.template[1]", "value": burst}]
        steps += [{"remove_link": "Kit Burst Spawner.spawner_values[0]"}] * n_values
        steps += [{"override": "Child Behaviour Dying", "from": common},
                  {"add_link": "Child Behaviour Dying.activates", "to": "Kit Burst Spawner"}]
    if lifetime is not None:
        src, timer = _LIFE_TIMER
        steps += [{"clone": [timer], "from": src, "rename": {timer: "Kit Life Timer"}},
                  {"set": "Kit Life Timer.duration", "value": float(lifetime)},
                  # Inherited, so named by its entity (as the clone's own timer
                  # chain ends: Death Tester -> Character_Common's state).
                  {"retarget": "Kit Life Timer.on_end",
                   "node": "Character_Common\\Character_Common.entity.ot|Behaviour Dying"},
                  {"override": "Child Event Initialize", "from": common},
                  {"add_link": "Child Event Initialize.activates", "to": "Kit Life Timer"}]
    if on_hit:
        # Each attack's impact moment (not a howl) starts a near-zero timer
        # into dying, as the life timer does; dying spawns the burst there.
        src, timer = _LIFE_TIMER
        hits = [c.name for c in EG.parse(out[model_ref]).components
                if c.cls == "oCEntityCpntStateSettings" and "Howl" not in c.name
                and re.match(r"^Event Attack .*Impact$", c.name)]
        if not hits:
            raise KitError(f"kit {slot}: burst_on_hit: this enemy has no 'Event Attack "
                           "... Impact' state to burst on")
        steps += [{"clone": [timer], "from": src, "rename": {timer: "Kit Burst Timer"}},
                  {"set": "Kit Burst Timer.duration", "value": 0.05},
                  {"retarget": "Kit Burst Timer.on_end",
                   "node": "Character_Common\\Character_Common.entity.ot|Behaviour Dying"}]
        steps += [{"add_link": f"{h}.activates", "to": "Kit Burst Timer"} for h in hits]
    # NPC_Common's wandering search looks for heroes (the hero layer), and
    # neither Ally_Model nor a pet base overrides it: a summon that went to
    # wander after spawning never found an enemy. Its own copy, flipped below.
    wander = "Wandering Target Traverser"
    if all(c.name != wander for c in EG.parse(out[model_ref]).components):
        steps.append({"override": wander, "from": "Enemies/NPC_Common/NPC_Common"})
    # NPC_Common warns before a spawn (2.5 s of summoning circle, the body
    # below ground), unless the base says not to: Hero_Pet_Model and Sun
    # Wukong's clone do; Ally_Model does not, so a summon lost 2.5 s of its
    # life before it could move.
    if not pet or burst:
        # Enemies target what stands on the hero layer. The wolf registers on
        # none of its own (Wolves_Model and Ally_Model have no GPN part), so no
        # enemy attacked it and it never died to burst (playtest 2026-11-03).
        # Sun Wukong's clone registers there with its own "GPN Hero". Its
        # "Targetable" flag is what enemies' target searches require
        # (NPC_Common's Fighting/Wandering Target Traversers test that flag
        # by name; no side bit). It reads the clone's own "Is Targetable
        # Condition", which _target_while_alive re-points after the steps.
        steps.append({"clone": ["GPN Hero"], "from": _LIFE_TIMER[0],
                      "rename": {"GPN Hero": "Kit GPN Hero"}})
        # And switched on as the clone does: while NPC_Common's "Child NPC
        # State GPN Active" holds (a copy nothing switched on registered
        # nowhere: enemies still ignored the wolf, playtest 2026-11-04).
        # A pet's chain to that state is cut: Hero_Pet_Model replaces
        # Character_Common's "State GPN Active" with one holding only soft
        # collision and detection (pets are meant to be invisible to enemies),
        # so NPC_Common's child states never run and the hook did nothing
        # (playtest 2026-11-04). A bomber pet gets Character_Common's own
        # state back, lower in the chain than the pet base's, so it wins.
        # Geppetto's dummy (an ally enemies attack and damage) is this exact
        # setup, with no side flag changed.
        if pet:
            steps.append({"override": "State GPN Active",
                          "from": "Character_Common/Character_Common"})
        gpn = "Child NPC State GPN Active"
        if all(c.name != gpn for c in EG.parse(out[model_ref]).components):
            steps.append({"override": gpn, "from": "Enemies/NPC_Common/NPC_Common"})
        steps.append({"add_link": f"{gpn}.while_active", "to": "Kit GPN Hero"})
    if not pet:
        warn = "Spawning Use Warning"
        if all(c.name != warn for c in EG.parse(out[model_ref]).components):
            steps.append({"override": warn, "from": "Enemies/NPC_Common/NPC_Common"})
        steps.append({"set": f"{warn}.value", "value": False})
    # An enemy rises out of the ground for 1.5 s (NPC_Common's appearance);
    # a summon appears as Sun Wukong's clone does, at once.
    appear = "Spawning Appearance Duration"
    if all(c.name != appear for c in EG.parse(out[model_ref]).components):
        steps.append({"override": appear, "from": "Enemies/NPC_Common/NPC_Common"})
    steps.append({"set": f"{appear}.value", "value": 0.1})
    if pet:
        # It notices enemies around its master on its own: Piper's rat looks
        # 20-30 m out while following, the pet base only 10.
        radius = "Fighting Target Detection Radius"
        if all(c.name != radius for c in EG.parse(out[model_ref]).components):
            steps.append({"override": radius, "from": "Enemies/NPC_Common/NPC_Common"})
        steps.append({"set": f"{radius}.value", "value": 20.0})
        # Where an attack order sends it: Hero_Pet_Model's "Attack Move Seed
        # Position" is empty (the world origin), so after the first order the
        # wolf walked off to nowhere and never fought again (playtest
        # 2026-11-03). Piper's rat reads her aim store into it; this one reads
        # the hero's "Kit Pet Centre" (its position, stored on every order),
        # aimed at the hero when the files are written (Copy.reads).
        seed, gv = "Attack Move Seed Position", "Kit Owner Seed Position"
        if all(c.name != seed for c in EG.parse(out[model_ref]).components):
            steps.append({"override": seed, "from": "Heroes/Hero_Pets/Hero_Pet_Model"})
        steps += [{"clone": ["Attack Seed Position Get Value"],
                   "from": "Heroes/Hero_Piper/Hero_Piper_Rat_Pet",
                   "rename": {"Attack Seed Position Get Value": gv}},
                  {"link": f"{seed}.value", "to": gv}]
        flag = "Alive Additional Flags Value"
        if all(c.name != flag for c in EG.parse(out[model_ref]).components):
            steps.append({"override": flag, "from": common})
        steps.append({"set": f"{flag}.value", "value": "Rat_Pet"})
    # An enemy waits between attacks so a pack does not swarm the hero (a
    # wolf: 3 s between any two, 1 s before the first); on our side that
    # left it standing by its target doing nothing.
    for c in EG.parse(out[model_ref]).components:
        if c.cls == "oCEntityCpntTimerSettings" and c.group == "Bhv Fighting" \
                and c.name.endswith("Attack Cooldown"):
            wait = 0.25 if "Start" in c.name else 1.0
            steps.append({"set": f"{c.name}.duration", "value": wait})
    # No enemy wind-up glow on our side (every summon, every attack).
    steps += _no_warnings(out[model_ref], m_stem)
    steps = [{**st, "entity": m_stem} for st in steps]
    if pet:
        steps += _pet_speed(out, model_ref, variant_ref)
    files = {m_stem: out[model_ref], v_stem: out[variant_ref]}

    def read(ref: str):
        return out.get(ref) or CK._corpus_reader(ref)
    try:
        res = AE.apply(files, steps, main=v_stem, seed=f"{v_stem}:end", read=read)
    except AE.AbilityEditError as e:
        raise KitError(f"kit {slot}: summon end: {e}") from None
    model = res.files[m_stem]
    if any(c.name == "Kit GPN Hero" for c in EG.parse(model).components):
        model = _target_while_alive(model, m_stem, slot)
    # The override and its sub-objects (its flag mask tester): every section
    # up to the next part.
    starts = sorted(c.index for c in EG.parse(model).components)
    k = next(c.index for c in EG.parse(model).components if c.name == wander)
    nxt = next((i for i in starts if i > k), None)
    model, _n = AS.flip_side(model, only=set(range(k, nxt if nxt is not None else 1 << 30)))
    return {model_ref: model, variant_ref: res.files[v_stem]}


#: What a summon's "Targetable" flag reads: Character_Common's own (inherited
#: by every character), the condition Geppetto's dummy (an ally enemies DO
#: attack) registers as its "Is Alive" flag.
_ALIVE = ("Character_Common\\Character_Common.entity.ot", "Is Alive Condition")


def _target_while_alive(model: bytes, m_stem: str, slot: str) -> bytes:
    """The summon's "Kit GPN Hero" "Targetable" flag reads "Is Alive
    Condition" instead of Sun Wukong's clone's "Is Targetable Condition".

    Enemies' target searches (NPC_Common's Fighting / Wandering Target
    Traversers) query the hero layer and require the "Targetable" flag; they
    test no side bit. The clone's condition is a HERO's: not concealed AND in
    Behaviour Default / Hit Stunned / Staggered. An NPC never enters Behaviour
    Default (it lives in Following / Fighting), so the flag was false all its
    life and no enemy aggroed the wolf or hit it (playtest 2026-11-05). Copied
    alone, the read also named a part the copy does not have."""
    from . import entity_check as CK
    from .entity_graph_edit import _B, _E, EntityFile, _lstr
    path, part = _ALIVE
    alive = next(c for c in EG.parse(CK._corpus_reader(path)).components if c.name == part)
    clone_raw = CK._corpus_reader(_LIFE_TIMER[0].replace("/", "\\") + ".entity.ot")
    clone = next(c for c in EG.parse(clone_raw).components if c.name == "Is Targetable Condition")
    ef = EntityFile(model, m_stem)
    gpn = ef.component("Kit GPN Hero")
    head = _B + struct.pack("<I", [x.name for x in ef.cf.classes].index("oCEntityCpntPicker"))
    label = f"[Cpnt Value Tester] Character_Common\\{alive.group}\\{part}"
    new = head + alive.guid + _lstr(label) + _E
    moved = 0
    for x in ef.subtree({gpn.index - 1}):
        p = ef.objects[x]
        i = p.find(head + clone.guid)
        if i < 0:
            continue
        end = i + 28 + struct.unpack_from("<I", p, i + 24)[0] + 4
        p[i:end] = new
        moved += 1
    if moved != 1:
        raise KitError(f"kit {slot}: summon: its GPN's Targetable flag read {moved} conditions, "
                       "expected Sun Wukong's clone's one")
    return ef.to_bytes()


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
    raw = copy.data if copy.data is not None else CK._corpus_reader(copy.source)
    if raw is None:
        raise KitError(f"{copy.source} is not in the game files")
    stem = copy.ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    ef = EntityFile(raw, stem)
    hero = {c.name: c for c in EG.parse(main).components}
    main_stem = main_ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    for gv, part in copy.reads.items():
        if part is None:
            # A part every hero has (Hero_Common's, Character_Common's): the
            # same link, read from this hero.
            ef.set_value(gv, "template[1]", main_ref)
            continue
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
