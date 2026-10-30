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
    slots = {}
    for slot in HK.SLOTS:
        none_ok, none_why, _ = tries({slot: "none"})
        fire_ok, fire_why, steps = tries({slot: {"fire": probe}})
        wolf_ok, _, wsteps = (tries({"form": "wolf", slot: {"fire": probe}}) if form_ok
                              else (False, "", []))
        slots[slot] = {"none": none_ok, "none_why": none_why, "fire": fire_ok,
                       "fire_why": fire_why,
                       "when": steps[-1]["add_link"].split(".")[0] if fire_ok else "",
                       "when_wolf": wsteps[-1]["add_link"].split(".")[0] if wolf_ok else ""}
    clips = [{"path": c, "name": c.rsplit("\\", 1)[-1].removesuffix(".fbx").replace("_", " ")}
             for c in HK.hero_clips(main)]
    return {"form": form_ok, "form_why": form_why, "slots": slots, "clips": clips}


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


def _bases(req: Request) -> dict:
    from rsmm.cli.editor import abilities as AB
    return {"heroes": AB._heroes()}


def _heroes_in(req: Request) -> dict:
    from rsmm.cli.editor import abilities as AB
    from rsmm.cli.editor import modio
    path = AB._manifest(req, req.arg("mod"))
    blocks = [c for c in modio._content(path.read_text(encoding="utf-8"))
              if c.get("kind") == "hero"]
    herodefs = {AB._herodef(h): h for h in AB._heroes()}
    return {"heroes": [{"id": c.get("id"), "base": herodefs.get(c.get("base"), c.get("base")),
                        "name": c.get("name") or c.get("id"),
                        "description": c.get("description") or "",
                        "kit": c.get("kit") or {}, "steps": len(c.get("abilities") or [])}
                       for c in blocks]}


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
    ("GET", "/api/mods"): _mods,
    ("GET", "/api/heroes"): _heroes_in,
    ("POST", "/api/save"): _save,
}
