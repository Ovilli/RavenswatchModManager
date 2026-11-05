"""`rsmm editor`'s Hero tab: make a hero of your own and put its abilities
together from building blocks (``engine/hero_kit.py``) instead of wiring parts.

A hero is a ``kind = "hero"`` block: identity (``base``, ``name``,
``description``) plus a ``[content.kit]`` table. Saving checks the kit builds on
its base (the same expansion and ability check ``rsmm apply`` runs) before
anything is written. Wiring the blocks cannot express stays in the Abilities
tab, which saves ``[[content.abilities]]`` steps into the same block.
"""

from __future__ import annotations

from functools import cache

from rsmm.cli.editor.app import Request

MOUNT = "hero"
PAGE = "hero.html"


def _main(base: str) -> bytes:
    from rsmm.engine import corpus
    raw = corpus.read(f"EntitySettings/Heroes/Hero_{base}/Hero_{base}.entity.ot"
                      ".EntitySettingsResource.gen")
    if raw is None:
        raise ValueError(f"no shipped hero {base!r}")
    return raw


@cache
def options(base: str) -> dict:
    """What each block can do on ``base``: ``form`` and, per slot, whether
    ``none`` and ``fire`` build, with the reason when not, and the state a
    fire goes off on. Found by expanding each block alone, so it is exactly
    what a save would accept."""
    from rsmm.engine import hero_kit as HK
    main = _main(base)
    stem = f"Hero_{base}"

    def tries(kit: dict) -> tuple[bool, str, list]:
        try:
            return True, "", HK.expand(kit, main, stem)
        except HK.KitError as e:
            return False, str(e).split(": ", 1)[-1], []

    form_ok, form_why, _ = tries({"form": "wolf"})
    probe = "Enemies/Tentacle_Nightmares/Projectile_Tentacle_Nightmare_Laser_Shot"
    clips = [{"path": c, "name": c.rsplit("\\", 1)[-1].removesuffix(".fbx").replace("_", " ")}
             for c in HK.hero_clips(main)]
    slots = {}
    for slot in HK.SLOTS:
        none_ok, none_why, _ = tries({slot: "none"})
        fire_ok, fire_why, steps = tries({slot: {"fire": probe}})
        wolf_ok, _, wsteps = (tries({"form": "wolf", slot: {"fire": probe}}) if form_ok
                              else (False, "", []))
        # Every block the page offers, tried alone on this slot: a built
        # ability needs a state to start on, Play animation a clip of the
        # slot's own to swap, Heal a heal of the base's to copy. Without these
        # the page offered blocks that could not save (Juliet's special,
        # Kintaro's power animation, any Snow Queen heal).
        build_ok, build_why, _ = tries({slot: {"replace": True, "steps": [{"wait": 0.1}]}})
        anim_kit = ({slot: {"replace": True, "steps": [{"anim": clips[0]["path"]}]}}
                    if clips else None)
        anim_ok, anim_why, _ = (tries(anim_kit) if anim_kit
                                else (False, "this hero has no animations to play", []))
        if anim_ok:
            # The swap itself is checked apart from the expansion (anim_swaps),
            # exactly as a save does.
            try:
                HK.anim_swaps(anim_kit, main, stem)
            except HK.KitError as e:
                anim_ok, anim_why = False, str(e).split(": ", 1)[-1]
        heal_ok, heal_why, _ = tries({slot: {"replace": True, "steps": [{"heal": 10}]}})
        slots[slot] = {"none": none_ok, "none_why": none_why, "fire": fire_ok,
                       "fire_why": fire_why,
                       "build": build_ok, "build_why": build_why,
                       "anim": anim_ok, "anim_why": anim_why,
                       "heal": heal_ok, "heal_why": heal_why,
                       "when": steps[-1]["add_link"].split(".")[0] if fire_ok else "",
                       "when_wolf": wsteps[-1]["add_link"].split(".")[0] if wolf_ok else "",
                       "states": _slot_states(main, slot)}
    return {"form": form_ok, "form_why": form_why, "slots": slots, "clips": clips,
            **_pet_options(base, main)}


def _slot_states(main: bytes, slot: str) -> list[str]:
    """The states a slot's ability runs through, human and alt form: what a
    pets block's ``when`` can name (Blood Wolf: "State Wolf Secondary Ability")."""
    from rsmm.engine import entity_graph as EG
    from rsmm.engine import hero_kit as HK
    word = HK.SLOTS[slot][0]
    groups = {f"Ability {word}", f"Ability Wolf {word}", f"Ability Alt {word}"}
    return sorted(c.name for c in EG.parse(main).components
                  if c.group in groups and c.cls == "oCEntityCpntStateSettings")


def _pet_options(base: str, main: bytes) -> dict:
    """What the Pets card and the Summon block pick from on ``base``: its
    talents' states (a talent that adds pets), its cards' String Formats (where
    the count shows) and the entities of its own folder (a burst)."""
    from rsmm.engine import corpus
    from rsmm.engine import entity_graph as EG
    g = EG.parse(main)
    states = {c.name for c in g.components if c.cls == "oCEntityCpntStateSettings"}
    talents = sorted(c.group for c in g.components
                     if c.cls.endswith("SkillControllerSettings") and c.group in states)
    if not talents:
        # A talent's state is the state named like its group ("Skill Secondary Ignite").
        talents = sorted(n for n in states if n.startswith("Skill ")
                         and any(c.group == n for c in g.components))
    cards = [{"part": c.name, "key": next((x for x in c.literals if "_Desc" in x), "")}
             for c in g.components if c.cls == "oCEntityCpntStringFormatValueSettings"
             and "Desc" in c.name and c.group != "Skills"]
    folder = f"EntitySettings/Heroes/Hero_{base}/"
    own = sorted(r.removeprefix("EntitySettings/").split(".entity.ot")[0]
                 for r in corpus.rels(folder, ".entity.ot.EntitySettingsResource.gen"))
    return {"talents": talents, "cards": sorted(cards, key=lambda c: c["part"]),
            "own_entities": [e for e in own if e != f"Heroes/Hero_{base}/Hero_{base}"]}


@cache
def summonables() -> list[dict]:
    """Shipped enemies a ``summon`` or ``pets`` block can turn into allies: a
    variant on a model of its own that sits on Enemy_Model (what
    ``engine/ally_summon.build`` copies and re-parents)."""
    from rsmm.engine import corpus
    from rsmm.engine import entity_components as EC
    from rsmm.engine.ally_summon import ENEMY_MODEL
    out = []
    for rel in corpus.rels("EntitySettings/Enemies/", ".entity.ot.EntitySettingsResource.gen"):
        path = rel.removeprefix("EntitySettings/").split(".entity.ot")[0]
        raw = corpus.read(rel)
        if not raw or path.endswith("_Model"):
            continue
        try:
            ps = EC.parents(raw)
        except Exception:      # noqa: BLE001 — a file the parent walk cannot read is not offered
            continue
        model = next((p for p in ps if p.endswith("_Model.entity.ot")), None)
        mraw = corpus.read(f"EntitySettings/{model.replace(chr(92), '/')}"
                           ".EntitySettingsResource.gen") if model else None
        if not mraw or ENEMY_MODEL not in EC.parents(mraw):
            continue
        out.append({"path": path, "name": path.rsplit("/", 1)[-1].replace("_", " "),
                    "group": path.split("/")[1].replace("_", " ")})
    return sorted(out, key=lambda x: (x["group"], x["name"]))


@cache
def enemy(path: str) -> dict:
    """An enemy's attacks (what ``attack`` names) and clips (what ``appear``
    plays instead of its spawn), read off its model."""
    import re

    from rsmm.engine import corpus
    from rsmm.engine import entity_components as EC
    from rsmm.engine import entity_graph as EG
    raw = corpus.read(f"EntitySettings/{path}.entity.ot.EntitySettingsResource.gen")
    if raw is None:
        raise ValueError(f"no shipped entity {path!r}")
    model = next((p for p in EC.parents(raw) if p.endswith("_Model.entity.ot")), None)
    mraw = corpus.read(f"EntitySettings/{model.replace(chr(92), '/')}"
                       ".EntitySettingsResource.gen") if model else None
    if not mraw:
        return {"attacks": [], "clips": []}
    names = {c.name for c in EG.parse(mraw).components}
    attacks = sorted(n[len("State Attack "):] for n in names if n.startswith("State Attack ")
                     and f"Attack {n[len('State Attack '):]} Condition" in names)
    clips = sorted({m.decode() for m in re.findall(rb"Characters\\[^\x00\"]+?\.fbx", mraw)
                    if not m.endswith(b"_Loop.fbx") and b"\\Animations\\" in m
                    and b"\\Additives\\" not in m})   # hit flinches, not a whole clip
    return {"attacks": attacks,
            "clips": [{"path": c, "name": c.rsplit("\\", 1)[-1].removesuffix(".fbx")
                       .replace("_", " ")} for c in clips]}


#: What a projectile does on its own, read off its parts' names.
_TAGS = (("homing", (b"State Homing", b"Homing Timer", b"Seeking", b"Follow Target")),
         ("pierce", (b"Piercing", b"Is Piercing")),
         ("lobbed", (b"Projectile_Lobbed_Model",)),
         ("explodes", (b"Explosion Radius", b"Explode Radius", b"Splash Attack")),
         ("ricochet", (b"Ricochet", b"Bounce")),
         ("returns", (b"Return Timer", b"Is Returning")))


@cache
def projectiles() -> list[dict]:
    """Shipped entities that fly or burst: what ``fire`` can shoot, by folder."""
    import re

    from rsmm.engine import corpus
    pat = re.compile(r"Projectile|Missile|Bolt|Shot|Wave|Bomb|Spike|Shockwave|Rain|Orb|"
                     r"Arrow|Fireball|Explosion", re.I)
    out = []
    for rel in corpus.rels("EntitySettings/", ".entity.ot.EntitySettingsResource.gen"):
        path = rel.removeprefix("EntitySettings/").split(".entity.ot")[0]
        top, *_, leaf = path.split("/")
        if top not in ("Enemies", "Heroes") or not pat.search(leaf) or "Warning" in leaf:
            continue
        raw = corpus.read(rel) or b""
        tags = [t for t, needles in _TAGS if any(x in raw for x in needles)]
        tags.append("hero" if top == "Heroes" or b"Hero_Projectile_Model" in raw else "enemy")
        out.append({"path": path, "name": leaf.replace("_", " "), "tags": tags,
                    "options": b"Projectile_Model\\" in raw,
                    "group": path.split("/")[1].replace("_", " ")})
    return sorted(out, key=lambda x: (x["group"], x["name"]))


def check(base: str, kit: dict) -> None:
    """Refuse a kit that would not build on ``base``."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import hero_kit as HK
    try:
        copies: list = []
        steps = HK.expand(kit, _main(base), f"Hero_{base}", copies=copies)
        HK.anim_swaps(kit, _main(base), f"Hero_{base}")
        if steps:
            AE.apply({f"Hero_{base}": _main(base)}, steps, main=f"Hero_{base}", seed="check",
                     read=HK.reader(copies))
    except (HK.KitError, AE.AbilityEditError) as e:
        raise ValueError(str(e)) from None


def _reads(path: str) -> list[dict]:
    """What a projectile reads from its own hero (a copy fires in its place,
    these numbers set by the block, defaulting to that hero's own)."""
    from rsmm.engine import hero_kit as HK
    return HK.owner_reads(HK._entity_ref(path))


def _bursts(kit: dict, old: str, new: str) -> dict:
    """``kit`` with every summon/pets ``burst`` that names ``old``'s own entity
    (``Heroes/Hero_Red/Hero_Red_Bomb``) naming ``new``'s instead. A hero of its
    own renames its base's family (Hero_Red_Bomb -> Hero_BloodWolf_Bomb, with
    the mod's own edits); the page lists the base's names, the kit must spawn
    the hero's (spawning the base's would burst Scarlet's unedited bomb)."""
    import json
    import re
    pat = re.compile(r'("burst": ")(Heroes/Hero_[^/"]+/)' + re.escape(old) + r"_")
    return json.loads(pat.sub(lambda m: m[1] + m[2] + new + "_", json.dumps(kit)))


def _bases(req: Request) -> dict:
    from rsmm.cli.editor import abilities as AB
    return {"heroes": AB._heroes()}


def _heroes_in(req: Request) -> dict:
    from rsmm.cli.editor import abilities as AB
    from rsmm.cli.editor import modio
    path = AB._manifest(req, req.arg("mod"))
    blocks = [c for c in modio._content(path.read_text(encoding="utf-8"))
              if c.get("kind") == "hero"]
    herodefs = {b: h for h in AB._heroes() for b in AB._bases(h)}
    out = []
    for c in blocks:
        base = herodefs.get(c.get("base"), c.get("base"))
        kit = _bursts(c.get("kit") or {}, f"Hero_{c.get('id')}", f"Hero_{base}")
        out.append({"id": c.get("id"), "base": base, "name": c.get("name") or c.get("id"),
                    "description": c.get("description") or "",
                    "kit": kit, "steps": len(c.get("abilities") or [])})
    return {"heroes": out}


def _save(req: Request) -> dict:
    """Create or update a hero: identity and kit, checked to build first."""
    import shutil

    from rsmm.cli.editor import abilities as AB
    from rsmm.cli.editor import content as C
    from rsmm.cli.editor import modio
    b = req.body
    base = str(b.get("base") or "")
    if base not in AB._heroes():
        raise ValueError(f"no shipped hero {base!r}")
    kit = b.get("kit") or {}
    if not isinstance(kit, dict):
        raise ValueError("kit is a table")
    name = str(b.get("hero_name") or "").strip()
    if not name:
        raise ValueError("give your hero a name")
    desc = str(b.get("hero_description") or "").strip()
    check(base, kit)
    created = bool(b.get("create"))
    mod_id = str(b.get("mod") or "")
    if created:
        meta = b.get("meta")
        C.save([], mod_id, req.ctx.mods_dir, create=True,
               meta=meta if isinstance(meta, dict) else None)
    try:
        path = AB._manifest(req, mod_id)
        block = str(b.get("block") or "")
        if not block:
            block = AB._add_hero(path, base, "custom", name=name, description=desc)
        text = path.read_text(encoding="utf-8")
        text = modio.set_hero_info(text, block, name=name, description=desc)
        kit = _bursts(kit, f"Hero_{base}", f"Hero_{block}")
        path.write_text(modio.set_hero_kit(text, block, kit), encoding="utf-8")
    except Exception:
        if created:
            shutil.rmtree(req.ctx.mods_dir / mod_id, ignore_errors=True)   # no half-made mod
        raise
    return {"mod": mod_id, "block": block}


def _mods(req: Request) -> dict:
    from rsmm.cli.editor import abilities as AB
    return AB._mods(req)


ROUTES = {
    ("GET", "/api/bases"): _bases,
    ("GET", "/api/options"): lambda req: options(req.arg("base")),
    ("GET", "/api/projectiles"): lambda req: {"projectiles": projectiles()},
    ("GET", "/api/reads"): lambda req: {"reads": _reads(req.arg("path"))},
    ("GET", "/api/summonables"): lambda req: {"enemies": summonables()},
    ("GET", "/api/enemy"): lambda req: enemy(req.arg("path")),
    ("GET", "/api/mods"): _mods,
    ("GET", "/api/heroes"): _heroes_in,
    ("POST", "/api/save"): _save,
}
