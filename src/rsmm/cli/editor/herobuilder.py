"""`rsmm editor`'s Hero tab: a hero written from scratch.

A hero of its own is a ``kind = "hero"`` block with no ``base``: identity
(``id``, ``name``, ``description``, ``memoirs``) and a ``[content.frame]``
table the SDK builds every file from (``sdk/kinds/heros.py::_emit_scratch``):
the rig that lends a skeleton, the body, the buttons, talents, ultimate
cards, projectiles, effects and animations of its own.

The page edits that block as data and sends it back whole; ``tomlblock``
writes only what changed, so a hand-commented manifest keeps its notes. Keys
the page has no form for travel through untouched.

Two checks: ``problems`` (every save; the fast, static half of what
``rsmm apply`` refuses: unknown keys, broken ``anim:``/``fx:``/``own:``
references, missing files, buttons the ability parser rejects) and ``build``
(on request; the real build into a throwaway folder, ~30 s for Jack).

Clone heroes (``base = ...``) are the Abilities tab's.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from rsmm.cli.editor.app import Request

MOUNT = "hero"
PAGE = "hero.html"

#: A scratch hero block's own keys (heros._emit_scratch refuses others).
TOP_KEYS = ("kind", "id", "name", "description", "memoirs", "frame")
#: What a button in the frame takes beyond Ability.parse's keys: its card
#: (name, description, icon) and two hooks the SDK lifts off before parsing.
BUTTON_EXTRA = ("name", "description", "icon", "icon_disabled", "steps", "add_stats")
#: Ability.parse keys the SDK fills itself, or that are temporary: not offered.
BUTTON_HIDDEN = frozenset({"bank", "name_key", "desc_key", "variant"})
TALENT_KEYS = ("name", "title", "description", "icon", "starter", "add_stats", "actions")
ULTIMATE_KEYS = ("title", "description", "icon", "add_stats", "actions")
#: A talent bonus (hero_frame.talent_effects -> talent_add_stat.add_stat).
ADD_STAT_KEYS = ("stat", "values", "percent", "during", "after", "on", "seconds",
                 "cooldown", "next")
ACTION_KEYS = ("on", "hits", "steps")
ANIMATION_KEYS = ("source", "clip", "template", "strict")
SLOT_KEYS = ("clip", "duration", "value", "bone", "texture")
LAYER_EXTRA = ("texture", "soft")
MEMOIR_KEYS = ("title", "text")
WEAPON_KEYS = ("from", "model", "albedo", "mesh", "material")
#: Hero_Common's six ultimate controllers: the cards every hero fills.
ULTIMATE_CARDS = ("Ultimate Power 1", "Ultimate 1 Upgrade 1", "Ultimate 1 Upgrade 2",
                  "Ultimate Power 2", "Ultimate 2 Upgrade 1", "Ultimate 2 Upgrade 2")
#: A talent's first word is its column in the book.
COLUMNS = ("Attack", "Power", "Special", "Defense", "Trait", "Dash", "Passive")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")
_REF = re.compile(r"^(anim|fx|own):(.+)$")
#: A `steps` entry is named by the first of these it has.
STEP_TYPES = ("fire", "hit", "heal", "summon", "anim", "wait", "repeat")


# --- what the page picks from ------------------------------------------------------

@cache
def schema() -> dict:
    """Every key set and choice the page offers, read off the code that
    consumes them so the page cannot drift from the build."""
    from rsmm.cli.editor import abilities as AB
    from rsmm.engine import hero_ability as HA
    from rsmm.engine import hero_kit as HK
    from rsmm.engine import projectile_frame as PF
    from rsmm.engine import talent_add_stat as TA
    from rsmm.engine import talent_status as TS
    from rsmm.engine import vfx_writer as VW
    from rsmm.engine._stat_keys_gen import STAT_KEYS
    from rsmm.sdk.kinds import heros
    button = sorted((HA.ABILITY_KEYS - BUTTON_HIDDEN) | set(BUTTON_EXTRA))
    return {
        "slots": list(HA.CONTROLLERS),
        "hold_slots": list(HA.RELEASE_INPUT),
        "charge_slots": list(HA.CHARGE_COUNTERS),
        "combo": {"min": HA.COMBO_STEPS, "max": HA.COMBO_MAX},
        "keys": {
            "top": list(TOP_KEYS),
            "frame": sorted(heros._SCRATCH_FIELDS),
            "button": button,
            "template": sorted((set(HA.TEMPLATE_KEYS) - BUTTON_HIDDEN)
                               | {"name", "description", "steps"}),
            "hit": ["at", *sorted(HA._HIT_KEYS - {"at"})],
            "combo": sorted(HA.COMBO_STEP_KEYS),
            "strike": sorted(HA.STRIKE_KEYS),
            "buff": sorted(HA.BUFF_KEYS),
            "indicator": sorted(HA._INDICATOR_KEYS),
            "talent": list(TALENT_KEYS),
            "ultimate": list(ULTIMATE_KEYS),
            "add_stat": list(ADD_STAT_KEYS),
            "action": list(ACTION_KEYS),
            "animation": list(ANIMATION_KEYS),
            "slot": list(SLOT_KEYS),
            "layer": sorted(VW.LAYER_KEYS | set(LAYER_EXTRA)),
            "projectile": sorted(PF.FIELDS),
            "memoir": list(MEMOIR_KEYS),
            "weapon": list(WEAPON_KEYS),
            "steps": {t: sorted(HK.STEP_KEYS[t]) for t in STEP_TYPES},
            "step_hit": sorted(HK.HIT_VALUES),
        },
        "enums": {
            "status": list(TS.STATUSES),
            "shake": list(HA.SHAKES),
            "stat": sorted({*STAT_KEYS, *_pseudo_stats()}, key=str.lower),
            "trigger": [*HA.CONTROLLERS, *TA.TRIGGERS],
            "ability": list(TA.ABILITIES),
        },
        "ultimates": list(ULTIMATE_CARDS),
        "columns": list(COLUMNS),
        "rigs": list(rigs()),
        # weapon.from names the hero's entity folder (SunWukong), not its alias
        "hero_folders": list(rigs().values()),
    }


@cache
def rigs() -> dict[str, str]:
    """Rig name (the alias the build takes: ``Hero_Sun_Wukong``) -> the hero's
    folder (``SunWukong``), for every shipped hero a rig may be: a paid DLC
    hero's art cannot be handed out, so Merlin is not offered."""
    from rsmm.cli.editor import abilities as AB
    from rsmm.sdk.kinds import heros

    def norm(s: str) -> str:
        return s.lower().replace("_", "")
    names: list[str] = []
    try:
        from rsmm.engine import hero_cook as H
        from rsmm.engine.paths import default_game_dir
        app = H.pristine_app_settings(default_game_dir())
        names = [a.name for a in H.aliases(app)] if app else []
    except Exception:        # noqa: BLE001 — without the alias table, folder names stand in
        names = []
    dlc = {norm(h) for h in heros.DLC_HEROES}
    out = {}
    for folder in AB._heroes():
        if norm(folder) in dlc:
            continue
        alias = next((n for n in names if n.startswith("Hero_")
                      and norm(n[5:]) == norm(folder)), f"Hero_{folder}")
        out[alias] = folder
    return out


@cache
def rig(name: str) -> dict:
    """What picking ``rig`` (``Hero_Kintaro``) suggests: its body mesh and
    material, and the animation slots it fills (what ``frame.slots`` can
    override)."""
    from rsmm.engine import corpus
    from rsmm.engine import hero_cook as H
    from rsmm.engine import hero_frame as HF
    from rsmm.sdk.kinds import heros
    if name not in rigs():
        raise ValueError(f"no shipped hero {name!r} to rig on")
    hero = rigs()[name]
    mesh = material = ""
    try:
        from rsmm.engine.paths import default_game_dir
        app = H.pristine_app_settings(default_game_dir())
        stem = heros.HD.stem(hero) or hero
        if app:
            b = H.resolve_base(stem, app)
            mesh, material = b.body_fbx or "", b.body_mat or ""
    except Exception:        # noqa: BLE001 — a suggestion; the folder scan below stands in
        pass
    if not mesh or not material:
        # Kintaro's herodef names his bear form: read his folder for the boy.
        found_mesh, found_mat = set(), set()
        for rel in corpus.rels(f"EntitySettings/Heroes/Hero_{hero}/",
                               ".EntitySettingsResource.gen"):
            raw = corpus.read(rel) or b""
            found_mesh |= {m.decode() for m in re.findall(
                rb"Characters\\Heroes\\[A-Za-z_]+\\[A-Za-z_]+_GEO\.fbx", raw)}
            found_mat |= {m.decode() for m in re.findall(
                rb"Characters\\Heroes\\[A-Za-z_]+\\Textures\\M_[A-Za-z_]+\.mat\.ot", raw)}
        pick = sorted(found_mesh, key=lambda m: ("Bear" in m or "Weapon" in m, len(m), m))
        mesh = mesh or (pick[0] if pick else "")
        mats = sorted(found_mat, key=lambda m: (len(m), m))
        material = material or (mats[0] if mats else "")

    def read(ref: str):
        return corpus.read(H.entity_rel(ref))
    try:
        slots = sorted(HF.rig_slots(read, f"Hero_{hero}"))
    except Exception:        # noqa: BLE001 — the page still takes any slot name
        slots = []
    portrait = ""
    try:
        from rsmm.engine import herodef_frame as HDF
        raw = heros.EP.corpus_read(heros._rel(heros.HD.stem(name.removeprefix("Hero_"))
                                              or heros.HD.stem(hero) or ""))
        portrait = HDF.decode(raw).root["portrait"][1] if raw else ""
    except Exception:        # noqa: BLE001 — the starter falls back to a default picture
        portrait = ""
    return {"mesh": mesh, "material": material, "slots": slots, "portrait": portrait,
            "bones": bones(mesh)}


@cache
def clips(mesh: str) -> dict:
    """The rig clips beside ``mesh``: what an animation's ``template`` names
    (``<its folder>\\Animations``, relative, no ``.fbx``: the folder the build
    looks in) and what a slot or button can play as shipped (full paths, from
    ``Animation`` too: Carmilla keeps hers there)."""
    from rsmm.engine import corpus
    if "\\" not in mesh:
        return {"templates": [], "clips": []}
    folder = mesh.rsplit("\\", 1)[0]
    out: dict[str, list[str]] = {"templates": [], "clips": []}
    for sub in ("Animations", "Animation"):
        here = f"{folder}\\{sub}"
        root = "3D/" + here.replace("\\", "/") + "/"
        for r in sorted(corpus.rels(root, ".Animation.gen")):
            rel = r[len(root):].removesuffix(".Animation.gen").replace("/", "\\")
            out["clips"].append(f"{here}\\{rel}")
            if sub == "Animations":
                out["templates"].append(rel.removesuffix(".fbx"))
    return out


@cache
def templates() -> list[dict]:
    """Every shipped button ``template`` can lend (``rsmm templates``): the
    name the page offers and every name it answers to."""
    from rsmm.engine import ability_template as AT
    from rsmm.engine import corpus
    from rsmm.engine import hero_cook as H
    return [{"name": f"{e.hero}: {e.names[0]}", "names": [f"{e.hero}: {n}" for n in e.names],
             "clips": e.clips}
            for e in AT.catalog(lambda ref: corpus.read(H.entity_rel(ref)))]


def _is_template(spec: str) -> bool:
    hero, _, button = str(spec).partition(":")
    name = f"{hero.strip().removeprefix('Hero_')}: {button.strip()}"
    return any(name in t["names"] for t in templates())


def _pseudo_stats() -> list[str]:
    """Talent bonuses that are not catalog stats (talent_add_stat handles them)."""
    from rsmm.engine import talent_add_stat as TA
    return [*TA.HELD_STATES, TA._MORE_BLEED, TA._CRIT_TO_DAMAGE]


def _stat_ok(stat) -> bool:
    from rsmm.engine import item_modifier as IM
    if isinstance(stat, str) and stat.strip().lower() in {s.lower() for s in _pseudo_stats()}:
        return True
    try:
        IM.resolve_stat(stat)
    except Exception:     # noqa: BLE001 — any refusal is the same answer
        return False
    return True


@cache
def projectiles() -> list[dict]:
    """Shipped entities that fly or burst: what a ``fire`` step can shoot."""
    from rsmm.engine import corpus
    pat = re.compile(r"Projectile|Missile|Bolt|Shot|Wave|Bomb|Spike|Shockwave|Rain|Orb|"
                     r"Arrow|Fireball|Explosion", re.I)
    out = []
    for rel in corpus.rels("EntitySettings/", ".entity.ot.EntitySettingsResource.gen"):
        path = rel.removeprefix("EntitySettings/").split(".entity.ot")[0]
        top, *_, leaf = path.split("/")
        if top in ("Enemies", "Heroes") and pat.search(leaf) and "Warning" not in leaf:
            out.append(path)
    return sorted(out)


@cache
def shipped() -> dict[str, list[str]]:
    """Every shipped name a text field can take, in the form the build reads,
    so nobody has to know them: effects, FX meshes and materials, enemies to
    summon, hand weapons and their materials, UI pictures. Read from the
    player's install; an install the corpus cannot list gives empty lists."""
    from rsmm.engine import corpus

    def rels(prefix: str, suffix: str) -> list[str]:
        try:
            return [r[len(prefix):-len(suffix)] for r in corpus.rels(prefix, suffix)]
        except Exception:        # noqa: BLE001 — no install: the fields stay free text
            return []
    bs = lambda s: s.replace("/", "\\")  # noqa: E731
    flying = set(projectiles())
    heroes3d = rels("3D/Characters/Heroes/", ".fbx.Geometry.gen")
    return {
        # FX/Settings/FX/Common_FX/X.vfx.ot -> Settings\FX\Common_FX\X.vfx.ot
        "effects": sorted(bs(f"Settings/{r}.vfx.ot")
                          for r in rels("FX/Settings/", ".vfx.ot.ScheduledVfxSettings.gen")),
        # mesh_ref takes a bare FX\Meshes name (letters, digits, _) or "decal".
        "fx_meshes": ["decal", *sorted(r for r in rels("FX/Meshes/", ".fbx.Geometry.gen")
                                       if r.replace("_", "").isalnum())],
        "fx_materials": sorted(bs(f"Materials/{r}.mat.ot")
                               for r in rels("FX/Materials/", ".mat.ot.Material.gen")),
        "enemies": sorted(p for p in (f"Enemies/{r}" for r in rels(
            "EntitySettings/Enemies/", ".entity.ot.EntitySettingsResource.gen"))
            if p not in flying and "Warning" not in p),
        # Hand weapons have no common name (Aladdin's is Aladdin_Sword): every hero mesh.
        "weapon_meshes": sorted(bs(f"Characters/Heroes/{r}.fbx") for r in heroes3d),
        "weapon_materials": sorted(bs(f"Characters/Heroes/{r}.mat.ot")
                                   for r in rels("3D/Characters/Heroes/", ".mat.ot.Material.gen")),
        # The cooked texture, not a .png: only a local mirror has the .png twin.
        "pictures": sorted(bs(f"Heroes/{r}.png")
                           for r in rels("Ui/Heroes/", ".png.Texture.dxt")),
        "sounds": sounds(),
    }


def sounds() -> list[str]:
    """Every FMod event part of a shipped (non-DLC) hero, as a ``sound`` field
    writes it: ``"<Folder\\Entity.entity.ot> | <part>"`` (hero_ability.own_sound)."""
    from rsmm.engine import corpus
    from rsmm.engine.entity_graph_edit import EntityFile
    from rsmm.sdk.kinds import heros
    dlc = {h.lower().replace("_", "") for h in heros.DLC_HEROES}
    pre, suf = "EntitySettings/", ".EntitySettingsResource.gen"
    out = []
    try:
        found = corpus.rels(pre + "Heroes/", ".entity.ot" + suf)
    except Exception:            # noqa: BLE001 — no install: the field stays free text
        return []
    for rel in found:
        ref = rel[len(pre):-len(suf)]
        folder = ref.split("/")[1].removeprefix("Hero_").lower().replace("_", "")
        if folder in dlc:
            continue
        try:
            raw = corpus.read(rel)
            stem = ref.rsplit("/", 1)[-1].removesuffix(".entity.ot")
            comps = EntityFile(raw, stem).graph().components
        except Exception:        # noqa: BLE001 — one unreadable file costs its sounds only
            continue
        ref = ref.replace("/", "\\")
        out += [f"{ref} | {c.name}" for c in comps if c.cls == "oCEntityCpntFModEventSettings"]
    return sorted(set(out))


def bones(mesh: str) -> list[str]:
    """The bone names of a shipped body mesh (what a slot's ``bone`` names)."""
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked, corpus
    from rsmm.engine import prop_cook as PC
    try:
        raw = corpus.read(PC.art_cooked_path(mesh)) if mesh else None
        return [b["name"] for b in CE.read_skeleton(cooked.parse(raw))] if raw else []
    except Exception:            # noqa: BLE001 — a suggestion list; the field still takes any name
        return []


def _mod_root(req: Request, mod_id: str) -> Path:
    """The mod's folder, or this page's draft folder before the mod exists."""
    from rsmm.cli.editor import herostarter as HS
    try:
        return HS._root(req, mod_id)
    except HS.StarterError as e:
        raise ValueError(str(e)) from None


def _files(req: Request) -> dict:
    """The mod's own source files a frame can name (``art/x.png``, a ``.glb``)
    (the page's draft folder's before there is a mod; listing makes none)."""
    if not req.arg("mod"):
        from rsmm.cli.editor import herostarter as HS
        try:
            root = HS.draft_dir(req.ctx.mods_dir, req.arg("draft"))
        except HS.StarterError as e:
            raise ValueError(str(e)) from None
        if not root.is_dir():
            return {"files": []}
    else:
        root = _mod_root(req, req.arg("mod"))
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or rel.parts[0] in ("assets",) or any(
                s.startswith(".") for s in rel.parts):
            continue
        if p.suffix.lower() in FILE_TYPES:
            out.append(rel.as_posix())
    return {"files": out, "sizes": {f: (root / f).stat().st_size for f in out}}


#: What the Files panel lists and serves, by extension.
FILE_TYPES = {".png": "image/png", ".glb": "model/gltf-binary", ".gltf": "model/gltf+json",
              ".fbx": "application/octet-stream", ".blend": "application/octet-stream"}


def _file_path(req: Request, rel: str) -> Path:
    """``rel`` inside the mod (or the page's draft): never outside it, never
    the manifest or the cooked ``assets/``."""
    if not req.arg("mod") and not req.body.get("mod"):
        from rsmm.cli.editor import herostarter as HS
        try:
            draft = req.arg("draft") or str(req.body.get("draft") or "")
            root = HS.draft_dir(req.ctx.mods_dir, draft)
        except HS.StarterError as e:
            raise ValueError(str(e)) from None
    else:
        root = _mod_root(req, req.arg("mod") or str(req.body.get("mod") or ""))
    parts = rel.replace("\\", "/").split("/")
    if not rel or any(x in ("", ".", "..") or x.startswith(".") for x in parts) \
            or parts[0] == "assets" or Path(rel).suffix.lower() not in FILE_TYPES:
        raise ValueError(f"not a file of the mod: {rel!r}")
    return root.joinpath(*parts)


def _file(req: Request):
    """A mod file's bytes, for the Files panel to show (a picture, a model)."""
    from rsmm.cli.editor.app import Fail, Raw
    f = _file_path(req, req.arg("path"))
    if not f.is_file():
        raise Fail(404, "no such file")
    return Raw(f.read_bytes(), FILE_TYPES[f.suffix.lower()])


def _static(req: Request):
    """three.js for the 3D preview: the Map tab's vendored copy."""
    from rsmm.cli.editor import maps
    return maps._static(req)


def _delete_file(req: Request) -> dict:
    f = _file_path(req, str(req.body.get("path") or ""))
    if not f.is_file():
        raise ValueError("no such file")
    f.unlink()
    return {"deleted": str(req.body.get("path"))}


# --- the block --------------------------------------------------------------------

def is_scratch(block: dict) -> bool:
    return block.get("kind") == "hero" and not block.get("base") \
        and isinstance(block.get("frame"), dict)


def _heroes(req: Request) -> dict:
    """The mod's heroes written from scratch, whole, and its clone heroes by name."""
    from rsmm.cli.editor import abilities as AB
    from rsmm.cli.editor import modio
    path = AB._manifest(req, req.arg("mod"))
    blocks = modio._content(path.read_text(encoding="utf-8"))
    return {"heroes": [b for b in blocks if is_scratch(b)],
            "others": [{"id": b.get("id"), "base": b.get("base")} for b in blocks
                       if b.get("kind") == "hero" and not is_scratch(b)]}


def _walk(v, where: str):
    """``(where, value)`` of every string in ``v``."""
    if isinstance(v, str):
        yield where, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from _walk(x, f"{where}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _walk(x, f"{where}[{i}]")


#: Fields that name a file of the mod (when not a ``\``-separated shipped path).
_FILE_FIELDS = {"albedo", "model", "source", "texture", "icon", "icon_disabled", "portrait",
                "banner", "new_hero", "skin_icon", "mra", "normal"}


def _mod_file(where: str, v: str) -> bool:
    leaf = re.sub(r"\[\d+\]$", "", where.rsplit(".", 1)[-1])
    return (leaf in _FILE_FIELDS and "\\" not in v and not _REF.match(v)
            and v.lower().endswith((".png", ".glb", ".gltf", ".fbx")))


def problems(hero: dict, root: Path | None = None) -> list[str]:
    """What ``rsmm apply`` would refuse about ``hero``, found without building."""
    from rsmm.engine import hero_ability as HA
    from rsmm.engine import hero_kit as HK
    from rsmm.sdk.kinds import heros
    out: list[str] = []
    say = out.append
    sch = schema()
    hid = str(hero.get("id") or "")
    if not _ID.match(hid):
        say("id: letters and digits, starting with a letter (e.g. JackSelf)")
    elif hid in heros._RESERVED_IDS or hid in heros.shipped_heroes():
        say(f"id: {hid!r} is a shipped hero's name; pick another")
    if extra := sorted(set(hero) - set(TOP_KEYS)):
        say(f"a hero written from scratch takes no {', '.join(extra)}")
    f = hero.get("frame")
    if not isinstance(f, dict):
        say("frame: missing")
        return out
    if extra := sorted(set(f) - heros._SCRATCH_FIELDS):
        say(f"frame: no {', '.join(extra)} (known: {', '.join(sorted(heros._SCRATCH_FIELDS))})")
    for k in ("rig", "mesh", "material"):
        if not f.get(k):
            say(f"frame.{k}: needed (pick a rig to fill the body in)")
    if f.get("rig") and f["rig"] not in sch["rigs"]:
        say(f"frame.rig: {f['rig']!r} is not a shipped hero")

    named = {"anim": set(f.get("animations") or {}), "fx": set(f.get("effects") or {}),
             "own": set(f.get("projectiles") or {}) | set(f.get("entities") or {})}
    what = {"anim": "animations", "fx": "effects", "own": "projectiles"}
    for where, v in _walk(hero, "hero"):
        m = _REF.match(v)
        if m and m[1] in named and m[2] not in named[m[1]]:
            say(f"{where[5:]}: no {what[m[1]]}.{m[2]} ({v})")
        elif root is not None and _mod_file(where, v) and not (root / v).is_file():
            say(f"{where[5:]}: no file {v} in the mod")

    def check_steps(steps, where: str) -> None:
        if steps is None:
            return
        if not isinstance(steps, list):
            say(f"{where}: a list of steps")
            return
        for n, st in enumerate(steps):
            kind = next((t for t in STEP_TYPES if isinstance(st, dict) and t in st), None)
            if kind is None:
                say(f"{where}[{n}]: one of {', '.join(STEP_TYPES)}")
                continue
            if extra := sorted(set(st) - HK.STEP_KEYS[kind]):
                say(f"{where}[{n}]: a {kind} step takes no {', '.join(extra)}")
            if kind == "repeat":
                check_steps(st.get("steps"), f"{where}[{n}].steps")

    def check_stats(stats, where: str) -> None:
        if stats is None:
            return
        if not isinstance(stats, list):
            say(f"{where}: a list of {{ stat, values }}")
            return
        for n, e in enumerate(stats):
            if not isinstance(e, dict) or not e.get("stat"):
                say(f"{where}[{n}]: needs stat")
                continue
            if extra := sorted(set(e) - set(ADD_STAT_KEYS)):
                say(f"{where}[{n}]: no {', '.join(extra)}")
            if not _stat_ok(e["stat"]):
                say(f"{where}[{n}]: no stat {e['stat']!r}")
            vals = e.get("values")
            if isinstance(vals, list) and len(vals) != 4:
                say(f"{where}[{n}]: values are 4, one per rarity (or one number for all)")

    def check_actions(actions, where: str) -> None:
        for n, a in enumerate(actions or []):
            if not isinstance(a, dict) or not a.get("on"):
                say(f"{where}[{n}]: needs on (when it fires)")
                continue
            if extra := sorted(set(a) - set(ACTION_KEYS)):
                say(f"{where}[{n}]: no {', '.join(extra)}")
            try:
                HA.parse_hits(placeholder(a.get("hits")), f"{where}[{n}]")
            except HA.AbilityError as e:
                say(str(e))
            check_steps(a.get("steps"), f"{where}[{n}].steps")

    def placeholder(v):
        """``anim:<name>`` / ``fx:<name>`` as the parser sees them once the
        build has made them: a clip path, an effect path."""
        if isinstance(v, str) and v.startswith("anim:"):
            return "Characters\\Own\\" + v[5:] + ".fbx"
        if isinstance(v, str) and v.startswith("fx:"):
            return "Settings\\Own\\" + v[3:] + ".vfx.ot"
        if isinstance(v, dict):
            return {k: placeholder(x) for k, x in v.items()}
        if isinstance(v, list):
            return [placeholder(x) for x in v]
        return v

    for slot, raw in (f.get("abilities") or {}).items():
        where = f"frame.abilities.{slot}"
        if slot not in HA.CONTROLLERS:
            say(f"{where}: no button {slot!r} ({', '.join(HA.CONTROLLERS)})")
            continue
        if not isinstance(raw, dict):
            say(f"{where}: a table")
            continue
        if raw.get("add_stats") and not raw.get("passive"):
            say(f"{where}: add_stats needs passive = true")
        check_stats(raw.get("add_stats"), f"{where}.add_stats")
        check_steps(raw.get("steps"), f"{where}.steps")
        parsed = placeholder({k: v for k, v in raw.items() if k not in BUTTON_EXTRA})
        if parsed.get("template") is not None:
            if not _is_template(parsed["template"]):
                say(f"{where}.template: no shipped button {parsed['template']!r}")
            continue
        try:
            HA.Ability.parse(slot, parsed)
        except HA.AbilityError as e:
            say(str(e))

    names: set[str] = set()
    for n, t in enumerate(f.get("talents") or []):
        where = f"frame.talents[{n}]"
        if not isinstance(t, dict) or not t.get("name"):
            say(f"{where}: needs a name")
            continue
        name = str(t["name"])
        if name in names:
            say(f"{where}: a second talent named {name!r}")
        names.add(name)
        if name.split(" ", 1)[0] not in COLUMNS:
            say(f"{where}: its name starts with its column ({', '.join(COLUMNS)})")
        if extra := sorted(set(t) - set(TALENT_KEYS)):
            say(f"{where}: no {', '.join(extra)}")
        check_stats(t.get("add_stats"), f"{where}.add_stats")
        check_actions(t.get("actions"), f"{where}.actions")
    for uname, u in (f.get("ultimates") or {}).items():
        where = f"frame.ultimates.{uname}"
        if uname not in ULTIMATE_CARDS:
            say(f"{where}: one of {', '.join(ULTIMATE_CARDS)}")
        if not isinstance(u, dict):
            continue
        if extra := sorted(set(u) - set(ULTIMATE_KEYS)):
            say(f"{where}: no {', '.join(extra)}")
        check_stats(u.get("add_stats"), f"{where}.add_stats")
        check_actions(u.get("actions"), f"{where}.actions")
    for name, a in (f.get("animations") or {}).items():
        if not isinstance(a, dict) or not a.get("source") or not a.get("template"):
            say(f"frame.animations.{name}: needs source (a .glb) and template (a rig clip)")
    from rsmm.engine import vfx_writer as VW
    layer_keys = VW.LAYER_KEYS | set(LAYER_EXTRA)
    for name, e in (f.get("effects") or {}).items():
        if not _ID.match(str(name)):
            say(f"frame.effects.{name}: a name of letters and digits")
        for n, layer in enumerate((e or {}).get("layers") or []):
            where = f"frame.effects.{name}.layers[{n}]"
            if not isinstance(layer, dict):
                say(f"{where}: a table")
                continue
            if extra := sorted(set(layer) - layer_keys):
                say(f"{where}: no {', '.join(extra)}")
            if not (layer.get("texture") or layer.get("material") or layer.get("light")):
                say(f"{where}: needs a texture, a shipped material or a light")
    from rsmm.engine import projectile_frame as PF
    for name, p in (f.get("projectiles") or {}).items():
        if not isinstance(p, dict) or not p.get("model"):
            say(f"frame.projectiles.{name}: needs a model (a .glb in the mod)")
        elif extra := sorted(set(p) - PF.FIELDS):
            say(f"frame.projectiles.{name}: no {', '.join(extra)}")
    for n, m in enumerate(hero.get("memoirs") or []):
        if not isinstance(m, dict) or set(m) - set(MEMOIR_KEYS):
            say(f"memoirs[{n}]: {{ title, text }}")
    return out


def _hero(req: Request) -> dict:
    hero = req.body.get("hero")
    if not isinstance(hero, dict):
        raise ValueError("hero is a table")
    hero = {**hero, "kind": "hero"}
    hero.pop("base", None)
    return {k: hero[k] for k in (*TOP_KEYS, *sorted(set(hero) - set(TOP_KEYS))) if k in hero}


def _check(req: Request) -> dict:
    try:
        root = _mod_root(req, str(req.body.get("mod") or ""))
    except ValueError:
        root = None
    return {"problems": problems(_hero(req), root)}


def _save(req: Request) -> dict:
    """Create or update a hero, every untouched line of its block kept."""
    import shutil

    from rsmm.cli.editor import abilities as AB
    from rsmm.cli.editor import content as C
    from rsmm.cli.editor import modio
    from rsmm.cli.editor import tomlblock as TB
    hero = _hero(req)
    hid = str(hero.get("id") or "")
    if not _ID.match(hid):
        raise ValueError("give your hero an id: letters and digits, starting with a letter")
    created = bool(req.body.get("create"))
    mod_id = str(req.body.get("mod") or "")
    if created:
        meta = req.body.get("meta")
        C.save([], mod_id, req.ctx.mods_dir, create=True,
               meta=meta if isinstance(meta, dict) else None)
    try:
        path = AB._manifest(req, mod_id)
        # Starter files and uploads made before there was a mod to put them in
        # (moved, never over a file the mod already has).
        from rsmm.cli.editor import herostarter as HS
        HS.take_draft(req.ctx.mods_dir, str(req.body.get("draft") or ""), path.parent)
        text = path.read_text(encoding="utf-8")
        block = str(req.body.get("block") or "")
        try:
            new = (TB.set_block(text, "hero", block, hero) if block
                   else TB.add_block(text, hero))
        except TB.BlockError as e:
            raise ValueError(str(e)) from None
        if block != hid and any(c.get("kind") == "hero" and c.get("id") == hid
                                for c in modio._content(text)):
            raise ValueError(f"this mod already has a hero {hid!r}")
        # Heroes are confirmed, but a hero written from scratch is not proven
        # in every part: the mod says so (rsmm lint wants the flag).
        new = modio._mark_experimental(new)
        path.write_text(new, encoding="utf-8")
    except Exception:
        if created:
            shutil.rmtree(req.ctx.mods_dir / mod_id, ignore_errors=True)   # no half-made mod
        raise
    return {"mod": mod_id, "block": hid, "problems": problems(hero, path.parent)}


def _delete(req: Request) -> dict:
    from rsmm.cli.editor import abilities as AB
    from rsmm.cli.editor import modio
    path = AB._manifest(req, str(req.body.get("mod") or ""))
    block = str(req.body.get("block") or "")
    text = path.read_text(encoding="utf-8")
    if not any(is_scratch(c) and c.get("id") == block for c in modio._content(text)):
        raise ValueError(f"no hero {block!r} written from scratch in this mod")
    path.write_text(modio.remove_blocks(text, {("hero", block)}), encoding="utf-8")
    return {"mod": path.parent.name}


def _build(req: Request) -> dict:
    """The real build of ``hero`` into a throwaway folder of the mod: exactly
    what ``rsmm apply`` would make of it, or why it would not."""
    import contextlib
    import io
    import shutil
    import tempfile
    import time

    hero = _hero(req)
    root = _mod_root(req, str(req.body.get("mod") or ""))
    return build_check(root, hero)


def build_check(root: Path, hero: dict) -> dict:
    """``hero`` built into a throwaway folder of the mod at ``root``."""
    import contextlib
    import io
    import shutil
    import tempfile
    import time

    from rsmm.sdk.content import ContentDef, ContentError
    from rsmm.sdk.kinds import heros
    out_dir = Path(tempfile.mkdtemp(prefix=".hero-check-", dir=root))
    log = io.StringIO()
    t0 = time.monotonic()
    try:
        fields = {k: v for k, v in hero.items() if k not in ("kind", "id")}
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            written = heros.emit(root.name, ContentDef("hero", str(hero.get("id")), fields),
                                 out_dir)
        ok, error, n = True, "", len(written)
    except (ContentError, ValueError, KeyError, OSError) as e:
        ok, error, n = False, str(e), 0
    except Exception as e:   # noqa: BLE001 — the page shows what broke, not a 500
        ok, error, n = False, f"{type(e).__name__}: {e}", 0
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    notes = [ln for ln in log.getvalue().splitlines() if ln.strip()]
    return {"ok": ok, "error": error, "files": n, "notes": notes[-200:],
            "seconds": round(time.monotonic() - t0, 1)}


def _mods(req: Request) -> dict:
    from rsmm.cli.editor import abilities as AB
    return AB._mods(req)


def _new_mod(req: Request) -> dict:
    """An empty mod, made before anything is saved: an upload or a starter
    file needs a folder to land in."""
    from rsmm.cli.editor import content as C
    mod_id = str(req.body.get("mod") or "")
    meta = req.body.get("meta")
    C.save([], mod_id, req.ctx.mods_dir, create=True, meta=meta if isinstance(meta, dict) else None)
    return {"mod": mod_id}


def _starter(fn):
    def route(req: Request):
        from rsmm.cli.editor import herostarter as HS
        try:
            return fn(HS)(req)
        except HS.StarterError as e:
            raise ValueError(str(e)) from None
    return route


#: Pure game-data reads: kept across launches, and by the web editor in the
#: browser (the shipped lists take seconds there).
CACHED = frozenset({"/api/schema", "/api/rig", "/api/clips", "/api/templates",
                    "/api/projectiles", "/api/shipped"})

ROUTES = {
    ("GET", "/api/schema"): lambda req: schema(),
    ("GET", "/api/rig"): lambda req: rig(req.arg("rig")),
    ("GET", "/api/clips"): lambda req: clips(req.arg("mesh")),
    ("GET", "/api/templates"): lambda req: {"templates": templates()},
    ("GET", "/api/projectiles"): lambda req: {"projectiles": projectiles()},
    ("GET", "/api/shipped"): lambda req: shipped(),
    ("GET", "/api/files"): _files,
    ("GET", "/api/mods"): _mods,
    ("GET", "/api/heroes"): _heroes,
    ("POST", "/api/check"): _check,
    ("POST", "/api/save"): _save,
    ("POST", "/api/delete"): _delete,
    ("POST", "/api/build"): _build,
    ("POST", "/api/newmod"): _new_mod,
    ("GET", "/api/file"): _file,
    ("POST", "/api/delete_file"): _delete_file,
    ("GET", "/static/*"): lambda req: _static(req),
    ("POST", "/api/upload"): _starter(lambda HS: HS.upload),
    ("POST", "/api/starter"): _starter(lambda HS: HS.starter),
    ("POST", "/api/starter_hero"): _starter(lambda HS: HS.hero),
    ("POST", "/api/recreate_hero"): _starter(lambda HS: HS.recreate),
}
