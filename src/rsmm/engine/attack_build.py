"""Custom attacks for a custom hero (``[[content.attacks]]`` on the hero kind).

An attack is declared, not wired by hand::

    [[content.attacks]]
    id       = "Crescent"             # letters/digits: Hero_<hero>_<id> is its entity
    slot     = "special"              # replaces that ability entirely
    model    = "art/crescent.glb"     # the projectile's mesh (static, glTF +Y = flight)
    albedo   = "art/crescent_alb.png" # its maps (mra / normal optional)
    scale    = 1.0
    speed    = 16                     # launch speed
    lifetime = 0.9                    # seconds before it expires
    beats    = [[0, 180], [90, -90]]  # beat -> angles (degrees, 0 = where she faces)
    delay    = 0.4                    # seconds between beats
    animation = "art/cast.glb"        # the slot's clip, played instead (+ `clip`)

WHAT IS HERS. The projectile is an entity of the hero's own
(``Hero_<hero>_<id>``) inheriting the engine's GENERIC hero projectile
(``Projectile_Model\\Hero_Projectile_Model``: physics, hit, piercing, damage,
despawn, network), and overriding only what an attack designer sets: its
mesh and material (cooked from the mod's files), lifetime, trail and impact
effects (the hero's own, recoloured by the hero kind's ``effects``) and sounds
(the base's own projectile sounds). The file it starts from is the smallest
shipped child of that model (a 9-part projectile), every part of which is
overridden; nothing of the hero it came from stays in play.

HOW IT IS FIRED. Each angle is a copy of the base's projectile spawner
together with its 3D node, the node's Y angle pointed at a value of the
attack's own: a spawner's own yaw fields are ignored for a hero ability spawn
(tried in game, 2026-09-26), the node is how the game fans Piper's notes.
Beat 0 fires when the slot activates; beat n on a timer ``n * delay`` later,
inside the slot's state (so the slot's animation must last that long).

Base-specific part names live in ``BASES``: a base not listed there cannot
host attacks yet (add its spawner/node/number/state/timer names).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import corpus
from . import entity_fields as EF
from .entity_graph_edit import EntityFile

TEMPLATE_REL = ("EntitySettings/Heroes/Hero_Red/"
                "Hero_Red_Projectile_Spike.entity.ot.EntitySettingsResource.gen")
TEMPLATE_MESH = "Characters\\Heroes\\RED\\Red_Dagger.fbx"
TEMPLATE_MAT = "Characters\\Heroes\\RED\\Textures\\M_Red_Dagger_Projectile.mat.ot"
TEMPLATE_TRAIL = "Settings\\Heroes\\Hero_Red_FX\\RED_Skill_Dash_Projectile_Trail_01.vfx.ot"
TEMPLATE_IMPACT = "Settings\\Heroes\\Hero_Red_FX\\RED_Impact_01.vfx.ot"
TEMPLATE_SOUNDS = ("Alive FMod Event Default", "Impact FMod Event Default")

FIELDS = {"id", "slot", "trigger", "replace", "model", "albedo", "mra", "normal",
          "scale", "speed", "lifetime", "beats", "delay", "trail", "impact",
          "animation", "clip"}


class AttackError(ValueError):
    pass


@dataclass(frozen=True)
class Slot:
    trigger: str                   # the state that fires when the ability is used
    replace: tuple[str, ...]       # the base's own effect links to cut from it
    clip: str                      # the ability's animation clip


@dataclass(frozen=True)
class BaseParts:
    """Names in the base hero's gameplay entity the builder copies."""
    spawner: str                   # a projectile spawner reading...
    node: str                      # ...this 3D node for its position/facing
    angle_ref: int                 # node.obj_4[n]: the node's Y-angle value
    offset_ref: int                # node.obj_4[n]: its sideways offset
    number: str                    # a plain f32 value to copy for our numbers
    beat_state: str                # a state to copy for a later beat
    timer: str                     # a timer to copy for a later beat
    projectile: str                # the base's projectile entity (its sounds)
    sounds: tuple[str, str]        # (alive, impact) sound parts in it
    trail: str                     # default trail effect (the base's own)
    impact: str                    # default impact effect
    slots: dict[str, Slot] = field(default_factory=dict)


BASES = {
    "Piper": BaseParts(
        spawner="Attack Shoot Projectile Spawner 02", node="Attack Shoot 3d Node 02",
        angle_ref=5, offset_ref=3,
        number="Primary Ability Shots Delay",
        beat_state="Event Secondary Ability Destroy Zone",
        timer="Ability Secondary Active Timer",
        projectile="Heroes\\Hero_Piper\\Hero_Piper_Projectile.entity.ot",
        sounds=("Alive FMod Event Night", "Impact FMod Event Night"),
        trail="Settings\\Heroes\\Hero_Piper_FX\\Piper_Skill_Ghost_Note_Trail.vfx.ot",
        impact="Settings\\Heroes\\Hero_Piper_FX\\Piper_Note_Impact_Light_Night.vfx.ot",
        slots={"special": Slot("Event Secondary Ability Activate",
                               ("Event Secondary Ability Activate.activates[0]",),
                               "Piper_Skill_Secondary_Static_Zone")}),
}


@dataclass
class Built:
    entity_rel: str                # where the projectile entity is written
    entity_ref: str                # how spawners and caches name it
    entity: bytes                  # its cooked bytes, before the hero's swaps
    steps: list[dict]              # ability steps (engine/ability_edit.py)
    animation: tuple[str, dict] | None   # (clip, {source, clip}) for `animations`


def _entity_rel(ref: str) -> str:
    return f"EntitySettings/{ref.replace(chr(92), '/')}.EntitySettingsResource.gen"


def _items(ef: EntityFile, comp: str, fld: str) -> int:
    f = next(x for x in EF.fields(ef.component(comp)) if x.name == fld)
    return len(f.items)


def _sound_guid(payload: bytes, where: str) -> int:
    """Offset of a sound event's 16-byte id: right after the bank name's lstr
    and 4 zero bytes (``oCFModDataDrivenEvent``; both Red's and Piper's)."""
    bank = b"DarkTales.bankset"
    i = payload.find(len(bank).to_bytes(4, "little") + bank)
    if i < 0:
        raise AttackError(f"{where}: no sound event in it")
    return i + 4 + len(bank) + 4


def build(spec: dict, *, hero: str, base: str, base_main: bytes, mesh, material) -> Built:
    """Compile one ``[[content.attacks]]`` table. ``mesh``/``material`` are the
    hero kind's helpers (they cook the mod's files and record preload lines)."""
    unknown = sorted(set(spec) - FIELDS)
    if unknown:
        raise AttackError(f"unsupported field(s) {unknown}; known: {sorted(FIELDS)}")
    aid = str(spec.get("id") or "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", aid):
        raise AttackError("an attack needs an `id` of letters and digits")
    parts = BASES.get(base)
    if parts is None:
        raise AttackError(f"attacks on a {base}-based hero are not mapped yet "
                          f"(have: {', '.join(sorted(BASES))})")
    slot = parts.slots.get(str(spec.get("slot") or ""))
    trigger = str(spec.get("trigger") or (slot.trigger if slot else ""))
    replace = spec.get("replace", list(slot.replace) if slot else [])
    if not trigger:
        raise AttackError(f"{aid}: give a `slot` ({', '.join(parts.slots)}) or a `trigger`")
    beats = spec.get("beats") or [[0]]
    if not (isinstance(beats, list) and all(isinstance(b, list) and b for b in beats)):
        raise AttackError(f"{aid}: `beats` is a list of angle lists, e.g. [[0, 180], [90, -90]]")
    if not spec.get("model"):
        raise AttackError(f"{aid}: an attack needs a `model` (its projectile's mesh)")

    # --- the projectile entity -------------------------------------------
    stem = f"Hero_{hero}_{aid}"
    ref = f"Heroes\\Hero_{base}\\{stem}.entity.ot"      # a shipped sibling folder
    raw = corpus.read(TEMPLATE_REL)
    if raw is None:
        raise AttackError("the projectile template is not in the game files")
    ef = EntityFile(raw, stem)
    ef.set_value("Lifetime Duration", "value", float(spec.get("lifetime", 1.0)))
    donor = corpus.read(_entity_rel(parts.projectile))
    if donor is None:
        raise AttackError(f"{parts.projectile} is not in the game files")
    def_ef = EntityFile(donor, parts.projectile.rsplit("\\", 1)[-1][:-len(".entity.ot")])
    for mine, theirs in zip(TEMPLATE_SOUNDS, parts.sounds, strict=True):
        src = bytes(def_ef.objects[def_ef.component(theirs).index - 1])
        dst = ef.objects[ef.component(mine).index - 1]
        a, b = _sound_guid(src, theirs), _sound_guid(bytes(dst), mine)
        dst[b:b + 16] = src[a:a + 16]
    tag = f"{hero}_{aid}"
    maps = {k: spec[k] for k in ("albedo", "mra", "normal") if spec.get(k)}
    transform = {"fit": "none", "scale": float(spec.get("scale", 1.0))}
    swaps = {TEMPLATE_MESH: mesh(TEMPLATE_MESH, spec["model"], tag, f"attacks.{aid}.model",
                                 transform),
             TEMPLATE_TRAIL: str(spec.get("trail") or parts.trail),
             TEMPLATE_IMPACT: str(spec.get("impact") or parts.impact)}
    if maps:
        swaps[TEMPLATE_MAT] = material(TEMPLATE_MAT, maps, tag, f"attacks.{aid}")
    from . import entity_strings as ES
    entity = ES.replace_strings(ef.to_bytes(), swaps)

    # --- the wiring -----------------------------------------------------
    main = EntityFile(base_main, "base")
    n_values = _items(main, parts.spawner, "spawner_values")
    n_state = _items(main, parts.beat_state, "activates")
    steps: list[dict] = [{"remove_link": r} for r in
                         sorted(replace, key=lambda s: -int(s.rsplit("[", 1)[1].rstrip("]")))]

    def number(suffix: str, value: float) -> str:
        steps.append({"clone": [parts.number], "suffix": f" {aid} {suffix}"})
        name = f"{parts.number} {aid} {suffix}"
        steps.append({"set": f"{name}.value", "value": value})
        return name

    zero = number("Zero", 0.0)
    speed = number("Speed", float(spec.get("speed", 16)))
    for bi, angles in enumerate(beats):
        spawners = []
        for k, deg in enumerate(angles):
            s = f" {aid} B{bi} {k}"
            sp, nd = parts.spawner + s, parts.node + s
            angle = number(f"B{bi} {k} Angle", math.radians(float(deg)))
            steps += [{"clone": [parts.spawner, parts.node], "suffix": s},
                      {"link": f"{nd}.obj_4[{parts.angle_ref}]", "to": angle},
                      {"link": f"{nd}.obj_4[{parts.offset_ref}]", "to": zero},
                      {"set": f"{sp}.template[1]", "value": ref},
                      {"link": f"{sp}.speed?", "to": speed}]
            steps += [{"remove_link": f"{sp}.spawner_values[0]"}] * n_values
            spawners.append(sp)
        if bi == 0:
            fire = trigger
        else:
            st, tm = parts.beat_state + f" {aid} B{bi}", parts.timer + f" {aid} B{bi}"
            steps.append({"clone": [parts.beat_state], "suffix": f" {aid} B{bi}"})
            steps += [{"remove_link": f"{st}.activates[0]"}] * n_state
            delay = number(f"B{bi} Delay", float(spec.get("delay", 0.4)) * bi)
            steps += [{"clone": [parts.timer], "suffix": f" {aid} B{bi}"},
                      {"link": f"{tm}.duration", "to": delay},
                      {"link": f"{tm}.on_tick", "to": st},
                      {"add_link": f"{trigger}.activates", "to": tm}]
            fire = st
        steps += [{"add_link": f"{fire}.activates", "to": sp} for sp in spawners]

    anim = None
    if spec.get("animation"):
        if not slot:
            raise AttackError(f"{aid}: `animation` needs a `slot` (its clip is replaced)")
        anim = (slot.clip, {"source": spec["animation"], "clip": spec.get("clip") or "cast"})
    return Built(_entity_rel(ref), ref, entity, steps, anim)
