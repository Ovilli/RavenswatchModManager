"""Files to start from, for the Hero tab: nobody should face an empty
``model = ""`` with no idea what goes there.

Each starter is written into the mod's own ``art/`` folder and is a real file
the player then edits (in Blender, in a paint program):

* ``body``: the rig's own body as a rigged ``.glb`` and its texture as a
  ``.png``, the starting point for a body of the hero's own;
* ``anim``: one rig clip on that body, as a ``.glb`` to re-pose;
* ``shape``: a white effect sprite (spark, puff, ring ...), drawn here;
* ``picture``: a UI picture the game ships (an icon, a portrait) as a ``.png``;
* ``projectile`` / ``weapon``: a shipped thrown dagger / the hand weapon of a
  shipped hero, as a ``.glb`` and its texture.

Everything is read from the player's own install (``corpus``) at the moment
they ask, so the repo ships no game file. ``hero`` is a whole starter hero on
a rig: buttons on the rig's clips, effects, talents, a book page, which builds
as it is.

Uploads land here too: ``upload`` writes a file the page sends into ``art/``.
"""

from __future__ import annotations

import base64
import math
import re
from pathlib import Path

from rsmm.cli.editor.app import Request

#: What an upload may be, by extension, and the bytes it must start with.
UPLOAD_KINDS = {".png": b"\x89PNG\r\n\x1a\n", ".glb": b"glTF", ".gltf": b"{",
                ".blend": b"BLENDER", ".fbx": b"Kaydara FBX Binary"}
#: Effect sprites drawn here: white shapes the layers tint.
SHAPES = ("spark", "puff", "dot", "ring", "slash", "streak", "leaf")
_SIZE = 128
_NAME = re.compile(r"[^A-Za-z0-9_.-]+")
#: A card with no picture of its own (the SDK's default icon).
DEFAULT_PICTURE = "Heroes\\Ultimate_Power_1_Default.png"


class StarterError(ValueError):
    pass


# --- where files go ------------------------------------------------------------------

#: Files made before the mod exists wait here, one folder per open page, and
#: move into the mod when it is saved (``take_draft``). A hidden folder with
#: no manifest: no tool takes it for a mod.
DRAFTS = ".hero-drafts"
_DRAFT_ID = re.compile(r"[A-Za-z0-9]{8,40}\Z")
#: A draft nobody saved is cleared after this long.
_DRAFT_DAYS = 2


def draft_dir(mods_dir: Path, draft: str) -> Path:
    if not _DRAFT_ID.match(draft or ""):
        raise StarterError("this page has no draft folder; reload it")
    return mods_dir / DRAFTS / draft


def _clear_old_drafts(mods_dir: Path) -> None:
    import shutil
    import time
    root = mods_dir / DRAFTS
    if not root.is_dir():
        return
    for d in root.iterdir():
        try:
            if time.time() - d.stat().st_mtime > _DRAFT_DAYS * 86400:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _root(req: Request, mod_id: str) -> Path:
    """The mod's folder, or, while the mod is not made yet (``mod`` empty),
    this page's draft folder: a starter or an upload needs no mod first."""
    from rsmm.cli.editor import abilities as AB
    if mod_id:
        return AB._manifest(req, mod_id).parent
    _clear_old_drafts(req.ctx.mods_dir)
    d = draft_dir(req.ctx.mods_dir, str(req.body.get("draft") or req.arg("draft")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def take_draft(mods_dir: Path, draft: str, mod_root: Path) -> None:
    """Move a draft's files into the mod just made (never over a file it has)."""
    import shutil
    try:
        src = draft_dir(mods_dir, draft)
    except StarterError:
        return
    if not src.is_dir():
        return
    for f in sorted(src.rglob("*")):
        if f.is_file():
            dest = mod_root / f.relative_to(src)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), dest)
    shutil.rmtree(src, ignore_errors=True)


def _folder(root: Path, folder: str) -> Path:
    clean = folder.replace("\\", "/").strip("/") or "art"
    parts = clean.split("/")
    if parts[0] != "art" or any(p in ("", ".", "..") for p in parts):
        raise StarterError("files go in the mod's art/ folder")
    d = root.joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(root: Path, folder: str, name: str, data: bytes, *, replace: bool = False) -> str:
    """Write ``data`` as ``art/<folder>/<name>`` (a free name unless ``replace``)
    and return its path relative to the mod."""
    d = _folder(root, folder)
    stem, dot, ext = name.rpartition(".")
    stem, ext = _NAME.sub("_", stem).strip("._-"), _NAME.sub("", ext).lower()
    if not dot or not stem or not ext:
        raise StarterError(f"{name!r} needs a name and an extension")
    dest, n = d / f"{stem}.{ext}", 2
    while dest.exists() and not replace:
        dest, n = d / f"{stem}_{n}.{ext}", n + 1
    dest.write_bytes(data)
    return dest.relative_to(root).as_posix()


def upload(req: Request) -> dict:
    """A file from the player's computer, into the mod's ``art/``."""
    b = req.body
    root = _root(req, str(b.get("mod") or ""))
    name = str(b.get("name") or "")
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in UPLOAD_KINDS:
        raise StarterError(f"a {', '.join(UPLOAD_KINDS)} file, not {name!r}")
    try:
        data = base64.b64decode(str(b.get("data") or ""), validate=True)
    except ValueError:
        raise StarterError("the file did not arrive whole; try again") from None
    if not data.startswith(UPLOAD_KINDS[ext]):
        raise StarterError(f"{name} is not a {ext} file inside")
    path = _write(root, str(b.get("folder") or "art"), name, data,
                  replace=bool(b.get("replace")))
    return {"path": path}


# --- drawn shapes ------------------------------------------------------------------------

def shape_png(shape: str, size: int = _SIZE) -> bytes:
    """A white sprite with its shape in the alpha: what an effect layer tints."""
    from rsmm.engine import image
    if shape not in SHAPES:
        raise StarterError(f"a shape is one of {', '.join(SHAPES)}")
    px = bytearray(size * size * 4)
    c = (size - 1) / 2
    for y in range(size):
        for x in range(size):
            dx, dy = (x - c) / c, (y - c) / c
            r = math.hypot(dx, dy)
            if shape == "dot":
                a = max(0.0, 1 - r) ** 1.5
            elif shape == "puff":
                ang = math.atan2(dy, dx)
                wob = 0.12 * math.sin(5 * ang) + 0.06 * math.sin(11 * ang)
                a = max(0.0, 1 - r / (0.85 + wob)) ** 0.8
            elif shape == "spark":
                a = max(0.0, 1 - r) ** 2 + max(0.0, 1 - abs(dx) * 14) * max(0.0, 1 - abs(dy)) \
                    + max(0.0, 1 - abs(dy) * 14) * max(0.0, 1 - abs(dx))
            elif shape == "ring":
                a = max(0.0, 1 - abs(r - 0.78) * 9)
            elif shape == "slash":
                # a crescent: the edge of a disc, thick in the middle, thin at the tips
                ang = math.atan2(dy, dx)
                band = max(0.0, 1 - abs(r - 0.75) / (0.02 + 0.16 * max(0.0, math.sin(ang))))
                a = band if dy < 0.15 else 0.0
            elif shape == "streak":
                a = max(0.0, 1 - abs(dy) * 7) * max(0.0, 1 - abs(dx)) ** 0.5
            else:   # leaf: a pointed ellipse with a vein
                body = (dx / 0.45) ** 2 + (dy / 0.95) ** 2
                a = 1.0 if body < 1 else 0.0
                if body < 1 and abs(dx) < 0.025:
                    a = 0.6
            a = min(1.0, a)
            i = (y * size + x) * 4
            px[i:i + 4] = bytes((255, 255, 255, int(a * 255)))
    return image.encode_png(size, size, bytes(px))


# --- from the game -------------------------------------------------------------------------

def _geo(mesh: str) -> bytes:
    from rsmm.engine import corpus
    from rsmm.engine import prop_cook as PC
    raw = corpus.read(PC.art_cooked_path(mesh)) if mesh else None
    if raw is None:
        raise StarterError(f"the game ships no mesh {mesh!r} (pick a rig first)")
    return raw


def _albedo_png(material: str, geo: bytes | None = None) -> bytes | None:
    from rsmm.engine import character_export as CE
    from rsmm.engine import cooked
    ref = CE.material_slots(material).get("ALB") if material else None
    if not ref and geo is not None:
        ref = next((r for r in CE.submesh_albedo_refs(cooked.parse(geo)) if r), None)
    return CE.texture_png(ref)


def body(root: Path, mesh: str, material: str) -> dict:
    """The rig's body as ``art/body.glb`` and its texture as ``art/body_alb.png``."""
    from rsmm.engine import character_export as CE
    geo = _geo(mesh)
    out = {"model": _write(root, "art", "body.glb", CE.export(geo, name="body"))}
    png = _albedo_png(material, geo)
    if png:
        out["albedo"] = _write(root, "art", "body_alb.png", png)
    return out


def body_albedo(root: Path, mesh: str, material: str) -> dict:
    png = _albedo_png(material, _geo(mesh))
    if not png:
        raise StarterError("the rig's texture could not be read")
    return {"albedo": _write(root, "art", "body_alb.png", png)}


def anim(root: Path, mesh: str, template: str) -> dict:
    """Rig clip ``template`` (``Kintaro_BasicAttack01``) on the rig's body, as
    ``art/anims/<clip>.glb``: the pose to start from. ``clip`` is its name
    inside the file; ``template`` stays the clip it was taken from."""
    from rsmm.engine import character_export as CE
    from rsmm.engine import corpus
    if "\\" not in mesh:
        raise StarterError("pick a rig first: the clip is taken from its skeleton")
    ref = f"{mesh.rsplit(chr(92), 1)[0]}\\Animations\\{template}.fbx"
    clip = corpus.read("3D/" + ref.replace("\\", "/") + ".Animation.gen")
    if clip is None:
        raise StarterError(f"the rig has no clip {template!r}")
    name = template.rsplit("\\", 1)[-1]
    glb = CE.export(_geo(mesh), {name: clip}, name=name, textures=False)
    return {"source": _write(root, "art/anims", f"{name}.glb", glb), "clip": name,
            "template": template}


def picture(root: Path, ref: str, name: str) -> dict:
    """A UI picture the game ships, as ``art/ui/<name>.png`` to paint over."""
    from rsmm.engine import character_export as CE
    ref = ref if "\\" in (ref or "") else DEFAULT_PICTURE
    png = CE.texture_png(ref, root="Ui")
    if png is None:
        png = CE.texture_png(DEFAULT_PICTURE, root="Ui")
    if png is None:
        raise StarterError(f"the game's picture {ref!r} could not be read")
    stem = name or ref.rsplit("\\", 1)[-1].removesuffix(".png")
    return {"path": _write(root, "art/ui", f"{stem}.png", png)}


def _rigid(root: Path, mesh: str, stem: str) -> dict:
    from rsmm.engine import character_export as CE
    geo = _geo(mesh)
    out = {"model": _write(root, "art/props", f"{stem}.glb", CE.export(geo, name=stem))}
    png = _albedo_png("", geo)
    if png:
        out["albedo"] = _write(root, "art/props", f"{stem}_alb.png", png)
    return out


def projectile(root: Path) -> dict:
    """Scarlet's thrown dagger: the mesh every projectile of a hero's own is
    cooked on, as a ``.glb`` to reshape."""
    from rsmm.engine import attack_build as AB
    return _rigid(root, AB.TEMPLATE_MESH, "projectile")


def weapon(root: Path, hero: str) -> dict:
    """``hero``'s right-hand weapon (Aladdin's sword) as a ``.glb``."""
    from rsmm.engine import corpus
    from rsmm.engine import hero_cook as H
    from rsmm.engine import hero_frame as HF
    from rsmm.engine.entity_graph_edit import EntityFile
    stem = f"Hero_{hero.removeprefix('Hero_')}"
    raw = corpus.read(H.entity_rel(f"Heroes\\{stem}\\{stem}.entity.ot"))
    if raw is None:
        raise StarterError(f"no shipped hero {hero!r}")
    try:
        body_ = EntityFile(raw, stem).component(HF.WEAPON_SLOT).body
    except Exception:     # noqa: BLE001 — a hero without one says so below
        body_ = b""
    found = re.search(rb"Characters\\[ -~]*?\.fbx", body_)
    if not found:
        raise StarterError(f"{hero} has no hand weapon to start from")
    return _rigid(root, found.group(0).decode(), "weapon")


def starter(req: Request) -> dict:
    """One starter file (``what``), written into the mod's ``art/``."""
    b = req.body
    root = _root(req, str(b.get("mod") or ""))
    what = str(b.get("what") or "")
    mesh, material = str(b.get("mesh") or ""), str(b.get("material") or "")
    if what == "body":
        return body(root, mesh, material)
    if what == "albedo":
        return body_albedo(root, mesh, material)
    if what == "anim":
        return anim(root, mesh, str(b.get("template") or ""))
    if what == "shape":
        shape = str(b.get("shape") or "")
        return {"path": _write(root, "art/fx", f"{shape}.png", shape_png(shape))}
    if what == "picture":
        return picture(root, str(b.get("ref") or ""), str(b.get("name") or ""))
    if what == "projectile":
        return projectile(root)
    if what == "weapon":
        return weapon(root, str(b.get("hero") or "Aladdin"))
    raise StarterError(f"no starter {what!r}")


# --- a whole hero -------------------------------------------------------------------------

#: Rig clips no button should play (moving, idling, dying, the book's poses,
#: a second form, a pet, a prop's own clip).
_NOT_A_MOVE = re.compile(r"Loop|Idle|Run|Walk|Death|Revive|Reviv|Stun|Teleport|Spawn|Interact|"
                         r"Book|Narrative|Facing|Bear_|Wolf|Rat|Wyrm|Fish_|Dismount|Hit_|Dash|"
                         r"_Mounted|_Out\b|_Out_|Physic|Wings|60FPS", re.I)
#: Per button, names to look for, best first.
_PREFER = {
    "attack1": [r"BasicAttack_?0?1\b", r"Attack.*(Step|Combo)_?1\b", r"Attack_(Default_)?0?1\b",
                r"Attack_Left", r"Attack.*_1\b", r"Attack"],
    "attack2": [r"BasicAttack_?0?2\b", r"Attack.*(Step|Combo)_?2\b", r"Attack_(Default_)?0?2\b",
                r"Attack_Right", r"Attack.*_2\b", r"Attack"],
    "power": [r"Power_In\b", r"Power_Default", r"Power(?!Hold)", r"Primary"],
    "special": [r"Special", r"Secondary", r"Skill"],
    "defense": [r"Defen"],
    "trait": [r"Trait"],
    "ultimate": [r"Ulti"],
}


def pick_clips(paths: list[str]) -> dict[str, str]:
    """A rig clip per button (full paths), by its name; another move where
    none is named so. Clips of a prop or pet (``RomeoRose_``) are skipped:
    only the hero's own prefix counts."""
    from collections import Counter
    leaf = {p: p.rsplit("\\", 1)[-1].removesuffix(".fbx") for p in paths}
    prefix = Counter(n.split("_", 1)[0] for n in leaf.values()).most_common(1)
    own = [p for p in paths if prefix and leaf[p].split("_", 1)[0] == prefix[0][0]]
    moves = [p for p in own if not _NOT_A_MOVE.search(p)] or own or list(paths)
    out, used = {}, set()
    for key, pats in _PREFER.items():
        hit = next((p for pat in pats for p in moves
                    if p not in used and re.search(pat, leaf[p], re.I)), None) \
            or next((p for p in moves if p not in used), None) or (moves[0] if moves else None)
        if hit:
            used.add(hit)
            out[key] = hit
    return out


def combo_step(clip: str, radius: float, damage: float) -> dict:
    """A combo step timed on its own clip: the next press must still have a
    tail to chain from after the exit (the build wants ~0.5 s of clip)."""
    from rsmm.engine import hero_frame as HF
    n = HF.clip_length(clip) or 1.0
    hit, link, leave = (round(min(v, n * f), 2) for v, f in ((0.25, 0.35), (0.35, 0.45),
                                                              (0.5, 0.6)))
    out = {"clip": clip, "hit_at": hit, "link_at": link, "exit_at": leave,
           "hits": [{"radius": radius, "damage": damage, "fx": "fx:Slash", "shake": "light"}]}
    if n < leave + 0.55:
        out["duration"] = round(leave + 0.55, 2)
    return out


def hero(req: Request) -> dict:
    """A starter hero on ``rig``: every button on a clip of the rig with hits and
    effects of its own, a few talents, an ultimate card and a book page. Writes
    its effect sprites into the mod's ``art/fx``."""
    from rsmm.cli.editor import herobuilder as HB
    b = req.body
    root = _root(req, str(b.get("mod") or ""))
    rig = HB.rig(str(b.get("rig") or ""))
    mesh, material = rig["mesh"], rig["material"]
    if not mesh:
        raise StarterError("that rig's body could not be found; pick another")
    clips = pick_clips(HB.clips(mesh)["clips"])
    if len(clips) < len(_PREFER):
        raise StarterError("that rig has too few clips to start from; pick another")
    tex = {s: _write(root, "art/fx", f"{s}.png", shape_png(s), replace=True)
           for s in ("spark", "puff", "ring", "slash")}
    effects = {
        "Slash": {"layers": [
            {"texture": tex["slash"], "mesh": "Fan_Flat_Large_180", "angle": 90, "burst": 1,
             "lifetime": 0.2, "size": 1.4, "colors": [[1, 0.95, 0.8, 1], [1, 0.8, 0.5, 0]],
             "grow": [0.85, 1.0]},
            {"light": 5, "burst": 1, "lifetime": 0.15, "size": 3,
             "colors": [[1, 0.9, 0.7, 1], [1, 0.9, 0.7, 0]]}]},
        "Burst": {"layers": [
            {"texture": tex["puff"], "soft": True, "burst": 8, "lifetime": [0.5, 0.8],
             "size": [1.2, 2.0], "speed": 6, "drag": 3, "colors": [[1, 0.85, 0.6, 0.8],
                                                                   [1, 0.6, 0.3, 0]],
             "grow": [0.6, 1.4]},
            {"texture": tex["spark"], "burst": 14, "lifetime": [0.3, 0.6], "size": [0.3, 0.5],
             "speed": 8, "up": 3, "gravity": 6, "drag": 2,
             "colors": [[1, 0.95, 0.7, 1], [1, 0.7, 0.3, 0]]},
            {"texture": tex["ring"], "burst": 1, "lifetime": 0.35, "size": 6,
             "colors": [[1, 0.9, 0.7, 0.9], [1, 0.9, 0.7, 0]], "grow": [0.2, 1.0]},
            {"light": 8, "burst": 1, "lifetime": 0.3, "size": 6,
             "colors": [[1, 0.8, 0.5, 1], [1, 0.8, 0.5, 0]]}]},
    }
    def card(name, desc):
        return {"name": name, "description": desc}

    from rsmm.engine import hero_frame as HF

    def length(key: str) -> float:
        return HF.clip_length(clips[key]) or 1.0

    def at(key: str, t: float) -> float:
        """``t`` s in, kept inside the clip (a hit after the button ends never lands)."""
        return round(min(t, length(key) * 0.7), 2)

    def step(key: str, radius: float, damage: float) -> dict:
        return combo_step(clips[key], radius, damage)
    abilities = {
        "attack": {**card("Strike", "• A quick two-hit combo"), "cooldown": 0.1, "combo": [
            step("attack1", 2.5, 140), step("attack2", 2.8, 180)]},
        "power": {**card("Shockwave", "• A burst around you that throws enemies back"),
                  "clip": clips["power"], "cooldown": 6,
                  "hits": [{"at": at("power", 0.3), "radius": 3.5, "damage": 300, "knockback": 50,
                            "fx": "fx:Burst", "shake": "medium"}],
                  "indicator": {"radius": 3.5}},
        "special": {**card("Whirl", "• Strike all around you twice"),
                    "clip": clips["special"], "cooldown": 8,
                    "hits": [{"at": at("special", 0.25), "radius": 3, "damage": 150,
                              "fx": "fx:Slash"},
                             {"at": at("special", 0.45), "radius": 3, "damage": 150,
                              "fx": "fx:Slash"}]},
        "defense": {**card("Stand Firm", "• #Stun@ and #Weaken@ enemies around you"),
                    "clip": clips["defense"], "cooldown": 10,
                    "hits": [{"at": at("defense", 0.2), "radius": 3, "damage": 100, "stun": 1.0,
                              "status": "Weak", "fx": "fx:Burst"}]},
        "trait": {**card("Snare", "• #Root@ enemies around you"),
                  "clip": clips["trait"], "cooldown": 12,
                  "hits": [{"at": at("trait", 0.3), "radius": 4, "damage": 120, "status": "Rooted",
                            "fx": "fx:Burst"}]},
        "ultimate": {**card("Finale", "• A huge blast that leaves enemies #Vulnerable@"),
                     "clip": clips["ultimate"], "cooldown": 60,
                     "hits": [{"at": at("ultimate", 0.4), "radius": 7, "damage": 1500, "stun": 1.5,
                               "status": "Vulnerable", "fx": "fx:Burst", "shake": "heavy"}]},
    }
    talents = [
        {"name": "Attack Keen Edge", "title": "Keen Edge",
         "description": "• #ATTACK@ gains &+{0}%~ #Crit Chance@", "starter": True,
         "add_stats": [{"stat": "Crit chance basic", "values": [0.08, 0.12, 0.16, 0.2]}]},
        {"name": "Power Quick Wave", "title": "Quick Wave",
         "description": "• #POWER@ cooldown is reduced by &{0}%~",
         "add_stats": [{"stat": "CD reduce primary", "values": [0.1, 0.15, 0.2, 0.25]}]},
        {"name": "Special Third Spin", "title": "Third Spin",
         "description": "• #SPECIAL@ spins once more for #200%@ damage",
         "actions": [{"on": "special", "hits": [{"at": 0.7, "radius": 3, "damage": 200,
                                                  "fx": "fx:Slash"}]}]},
        {"name": "Passive Tough Skin", "title": "Tough Skin",
         "description": "• Gain &+{0}~ #ARMOR@", "starter": True,
         "add_stats": [{"stat": "Armour", "values": [5, 8, 11, 15], "percent": False}]},
    ]
    # Its own portrait, a copy of the rig's to paint over: a rig's shipped one
    # is not always in a preload list (Piper's), and the build refuses those.
    portrait = picture(root, rig.get("portrait") or "", "portrait")["path"]
    return {"frame": {
        "rig": str(b.get("rig")), "mesh": mesh, "material": material, "portrait": portrait,
        "effects": effects, "abilities": abilities, "talents": talents,
        "ultimates": {"Ultimate Power 1": {"title": "Finale",
                                           "description": abilities["ultimate"]["description"]}},
    }, "memoirs": [{"title": "Chapter One", "text": "Write your hero's story here."}]}


# --- a shipped hero, rebuilt from scratch ---------------------------------------------------

#: Per button: its card's text key word, its icon's last word, its column word.
_SLOTS = {"attack": ("Attack", ("Attack",)), "power": ("Power", ("Power",)),
          "special": ("Special", ("Special",)), "defense": ("Defense", ("Defensive", "Defense")),
          "trait": ("Trait", ("Trait",)), "ultimate": ("Ultimate_1", ("Ultimate_1",))}
#: A talent's column -> its stand-in effects, by turns: (stat, card line, values per rarity).
_CD, _AP = [0.1, 0.15, 0.2, 0.25], [0.15, 0.2, 0.3, 0.4]


def _button_fx(stat: str, label: str) -> list[tuple]:
    return [(f"CD reduce {stat}", f"#{label}@ cooldown is reduced by &{{0}}%~", _CD),
            (f"Attack power {stat}", f"#{label}@ deals &+{{0}}%~ damage", _AP)]


_TALENT_FX = {
    "Attack": [("Attack power basic", "#ATTACK@ deals &+{0}%~ damage", [0.1, 0.15, 0.2, 0.25]),
               ("Crit chance basic", "#ATTACK@ gains &+{0}%~ #Crit Chance@",
                [0.08, 0.12, 0.16, 0.2])],
    "Power": _button_fx("primary", "POWER"),
    "Special": _button_fx("secondary", "SPECIAL"),
    "Defense": _button_fx("defensive", "DEFENSE"),
    "Trait": _button_fx("trait", "TRAIT"),
    "Dash": [("CD reduce dash", "#DASH@ cooldown is reduced by &{0}%~", _CD),
             ("Crit chance dash", "#DASH@ gains &+{0}%~ #Crit Chance@", _CD)],
    "Passive": [("Armour", "Gain &+{0}~ #ARMOR@", [5, 8, 11, 15]),
                ("Crit chance", "Gain &+{0}%~ #Crit Chance@", [0.04, 0.06, 0.08, 0.1]),
                ("Attack power", "Deal &+{0}%~ damage", [0.05, 0.08, 0.11, 0.15]),
                ("Crit damage", "Gain &+{0}%~ #Crit Damage@", _CD)],
    "Ultimate": [("Attack power ultimate", "#ULTIMATE@ deals &+{0}%~ damage", _AP),
                 ("CD reduce ultimate", "#ULTIMATE@ cooldown is reduced by &{0}%~", _CD)],
}
_FLAT = {"Armour"}


def _bank(decoded: str) -> dict[str, str]:
    """A text bank of the install (``Text/<name>~GAM.xls``) as key -> English."""
    from rsmm.cli.apply_mods import find_game_dir
    from rsmm.engine import text_patches as TP
    from rsmm.engine.asset_map import decoded_to_encoded
    from rsmm.engine.paths import COOKING_REL
    game = find_game_dir()
    enc = decoded_to_encoded().get(f"Text/{decoded}.LocalText.gen") if game else None
    if not enc:
        return {}
    path = game / COOKING_REL / Path(*enc.split("\\"))
    try:
        keys = TP.parse_text_file(path).entries
        vals = TP.parse_text_file(TP.lang_path_for(path, "EN")).entries
    except (OSError, ValueError):
        return {}
    return dict(zip(keys, vals, strict=False))


def _hit_line(hits: list[dict]) -> str:
    """A button's card text, written from what it does."""
    out = []
    for h in hits or []:
        r, d = h.get("radius", 0), h.get("damage", 0)
        line = f"• Hits enemies within #{r:g} m@ for #{d:g}%@ damage"
        if h.get("stun"):
            line += f" and #Stuns@ them for {h['stun']:g} s"
        if h.get("status"):
            line += f", leaving them #{h['status']}@"
        out.append(line)
    return "\n".join(dict.fromkeys(out))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _talent_icon(pics: set[str], card: dict) -> str:
    """The shipped icon of a talent card: ``Skill <source>.png`` as most are
    named, else the one whose name matches the card's source or text key."""
    want = {_norm("Skill " + str(card.get("source") or "")), _norm(str(card.get("base") or ""))}
    return next((p for p in sorted(pics) if _norm(p) in want), "")


def _shipped_picture(root: Path, ui: str, stem: str, name: str) -> str:
    """``Ui/Heroes/<ui>/<stem>.png`` copied into the mod, or "" when the game has none."""
    from rsmm.engine import corpus
    if not stem or not corpus.exists(f"Ui/Heroes/{ui}/{stem}.png.Texture.dxt"):
        return ""
    try:
        return picture(root, f"Heroes\\{ui}\\{stem}.png", name)["path"]
    except StarterError:
        return ""


def recreate(req: Request) -> dict:
    """The shipped hero on ``rig``, rebuilt as a hero of one's own: every file
    it uses is written into the mod (body, texture, each move as a clip, button
    and talent icons, portrait, banner, weapon), its cards carry the game's own
    names, and its moves are rebuilt from scratch as hits on its real clips.
    The moves are close, not exact: the kit has hits, not every shipped trick."""
    from rsmm.cli.editor import content as C
    from rsmm.cli.editor import herobuilder as HB
    from rsmm.engine import corpus
    from rsmm.engine import hero_ability as HA
    from rsmm.engine import herodef_frame as HDF
    from rsmm.sdk.kinds import heros

    b = req.body
    rig_name = str(b.get("rig") or "")
    root = _root(req, str(b.get("mod") or ""))
    base = hero(req)                          # its effects, its buttons on its own clips
    frame = base["frame"]
    start_clips = {k: a.get("clip", "") for k, a in frame["abilities"].items()}
    rig = HB.rig(rig_name)
    mesh, material = rig["mesh"], rig["material"]
    folder = HB.rigs()[rig_name]
    portrait = rig.get("portrait") or ""
    ui = portrait.split("\\")[1] if portrait.count("\\") >= 2 else folder
    notes: list[str] = []

    # Its body and texture, as its own files.
    frame.update(body(root, mesh, material))

    # Its whole basic-attack chain, not two steps of it.
    rig_clips = HB.clips(mesh)
    own = pick_clips(rig_clips["clips"])
    prefix = own["attack1"].rsplit("\\", 1)[-1].split("_", 1)[0] if own.get("attack1") else ""
    chain = sorted(p for p in rig_clips["clips"]
                   if re.search(r"BasicAttack_?0?\d\b", p) and not _NOT_A_MOVE.search(p)
                   and p.rsplit("\\", 1)[-1].startswith(prefix + "_"))[:HA.COMBO_MAX]
    if len(chain) >= HA.COMBO_STEPS:
        damage = [140, 160, 200, 260][:len(chain)]
        frame["abilities"]["attack"]["combo"] = [
            combo_step(c, 2.5 + 0.2 * n, d)
            for n, (c, d) in enumerate(zip(chain, damage, strict=True))]

    # Every move it plays, written out as its own clip; the buttons play those.
    here = mesh.rsplit("\\", 1)[0]
    templates = {f"{here}\\Animations\\{t}.fbx": t for t in rig_clips["templates"]}
    animations: dict[str, dict] = {}

    def own_clip(path: str) -> str:
        t = templates.get(path)
        if not t:
            note = ("its moves (this rig keeps its clips where a clip of one's own "
                    "cannot take them from)")
            if note not in notes:
                notes.append(note)
            return path
        name = t.rsplit("\\", 1)[-1]
        if name not in animations:
            try:
                animations[name] = anim(root, mesh, t)
            except Exception as e:   # noqa: BLE001 — that move keeps the game's clip
                notes.append(f"{name}: {e}")
                return path
        return f"anim:{name}"
    for ab in frame["abilities"].values():
        if ab.get("clip"):
            ab["clip"] = own_clip(ab["clip"])
        for st in ab.get("combo") or []:
            st["clip"] = own_clip(st["clip"])
    frame["animations"] = {n: {"source": a["source"], "clip": a["clip"], "template": a["template"]}
                           for n, a in animations.items()}

    # Its cards: the game's own names, text written from what each button does,
    # its own icons (and their greyed copies).
    from rsmm.sdk.kinds import skills as SK
    common = SK._install_bank(C._herodefs().get(folder, folder))
    text = _bank(common[1].removeprefix("Text/").removesuffix(".LocalText.gen")) if common else {}
    # Listed by the cooked texture: a player's install has no .png twin.
    suffix = ".png.Texture.dxt"
    pics = {r.rsplit("/", 1)[-1][:-len(suffix)] for r in corpus.rels(f"Ui/Heroes/{ui}/", suffix)}
    for slot, (word, icon_words) in _SLOTS.items():
        ab = frame["abilities"].get(slot)
        if not ab:
            continue
        name = next((text[k] for k in (f"Ability_{word}_Name", f"Ability_Dismounted_{word}_Name",
                                       f"Ability_Mounted_{word}_Name") if text.get(k)), "")
        if name.strip():
            ab["name"] = name.strip()
        hits = ab.get("hits") or [h for st in ab.get("combo") or [] for h in st.get("hits", [])]
        if hits:
            ab["description"] = _hit_line(hits)
        icons = sorted(p for p in pics if p.startswith("Ability_") and not p.endswith("_Disabled")
                       and p.endswith(tuple("_" + w for w in icon_words)))
        icons.sort(key=lambda p: "Dismounted" not in p)    # the form a rig body is
        if icons:
            got = _shipped_picture(root, ui, icons[0], f"{slot}_icon")
            if got:
                ab["icon"] = got
                grey = _shipped_picture(root, ui, icons[0] + "_Disabled", f"{slot}_icon_disabled")
                if grey:
                    ab["icon_disabled"] = grey

    # Its talents: every card of the hero, by its own name and icon; what each
    # does is a stand-in of its column (the card says what it really does here).
    cards = C.talent_cards(folder)
    turn: dict[str, int] = {}
    talents, ultimates, starters = [], {}, set()
    ult_upgrades = []
    for c in cards:
        base_key, source = str(c.get("base") or ""), str(c.get("source") or "")
        column = source.split(" ", 1)[0]
        if base_key.startswith("Skill_Ultimate"):
            m = re.fullmatch(r"Skill_Ultimate_(\d)(?:_(\w+))?", base_key)
            if m and m.group(1) == "1":
                if m.group(2):
                    ult_upgrades.append(c)
                else:
                    ultimates["Ultimate Power 1"] = {
                        "title": c["name"],
                        "description": frame["abilities"]["ultimate"].get("description", "")}
            continue
        if column not in _TALENT_FX:
            continue
        stat, line, values = _TALENT_FX[column][turn.get(column, 0) % len(_TALENT_FX[column])]
        turn[column] = turn.get(column, 0) + 1
        t = {"name": source, "title": c["name"], "description": "• " + line,
             "add_stats": [{"stat": stat, "values": values,
                            **({"percent": False} if stat in _FLAT else {})}]}
        if column in ("Attack", "Power", "Passive") and column not in starters:
            t["starter"] = True
            starters.add(column)
        word = re.sub(r"\W+", "_", source)
        icon = _shipped_picture(root, ui, _talent_icon(pics, c), f"talent_{word}")
        if icon:
            t["icon"] = icon
        talents.append(t)
    if talents:
        frame["talents"] = talents
    for n, c in enumerate(ult_upgrades[:2], 1):
        # An ultimate card has no rarity, so no per-rarity number: a flat stat.
        stat, line, values = _TALENT_FX["Ultimate"][(n - 1) % 2]
        amount = values[-1]
        u = {"title": c["name"], "description": "• " + line.replace("&+{0}%~", f"#+{amount:.0%}@")
             .replace("&{0}%~", f"#{amount:.0%}@"),
             "add_stats": [{"stat": stat, "values": amount}]}
        icon = _shipped_picture(root, ui, _talent_icon(pics, c), f"ultimate_upgrade_{n}")
        if icon:
            u["icon"] = icon
        ultimates[f"Ultimate 1 Upgrade {n}"] = u
    if ultimates:
        ult_icon = frame["abilities"]["ultimate"].get("icon")
        if ult_icon and "Ultimate Power 1" in ultimates:
            ultimates["Ultimate Power 1"]["icon"] = ult_icon
        frame["ultimates"] = {**frame.get("ultimates", {}), **ultimates}

    # Its banner and hand weapon, as its own files.
    banner = next((p for p in sorted(pics) if p.startswith("HUD_Banner")), "")
    if banner:
        got = _shipped_picture(root, ui, banner, "banner")
        if got:
            frame["banner"] = got
    try:                             # `from` is the entity folder (SunWukong, not Sun_Wukong)
        frame["weapon"] = {"from": folder, **weapon(root, folder)}
    except StarterError as e:
        notes.append(str(e))

    # Its book: the hero's own seven pages.
    memoirs = base["memoirs"]
    try:
        raw = heros.EP.corpus_read(heros._rel(heros.HD.stem(folder) or folder))
        pages = [d for c, d in HDF.decode(raw).objects if c == HDF.STORY] if raw else []
        books: dict[str, dict] = {}
        got = []
        for d in pages:
            bank = d["title"].bank.removesuffix(".LocalText.gen")
            books.setdefault(bank, _bank(bank))
            title, body_ = books[bank].get(d["title"].key, ""), books[bank].get(d["desc"].key, "")
            if title or body_:
                got.append({"title": title, "text": body_})
        memoirs = got or memoirs
    except Exception as e:           # noqa: BLE001 — the book keeps the starter's page
        notes.append(f"book: {e}")

    name = text.get("Hero_Name") or folder
    hid = re.sub(r"[^A-Za-z0-9]", "", folder) + "Scratch"
    info = {"name": f"{name} (from scratch)", "id": hid, "description": text.get("Hero_Desc", "")}
    _settle(root, {"kind": "hero", **info, "frame": frame, "memoirs": memoirs}, start_clips, notes)
    return {"frame": frame, "memoirs": memoirs, "notes": notes, "hero": info}


def _settle(root: Path, hero: dict, start_clips: dict, notes: list[str], tries: int = 6) -> None:
    """Build ``hero`` for real and give back to the game each part the build
    refuses (a weapon whose look cannot be lent, a move that does not fit the
    body's skeleton), so what the page gets always builds. Each is noted."""
    from rsmm.cli.editor import herobuilder as HB
    frame = hero["frame"]
    for _ in range(tries):
        err = HB.build_check(root, hero)["error"]
        if not err:
            return
        m = re.search(r"animation (\S+?):", err)
        if "weapon" in err and frame.get("weapon"):
            del frame["weapon"]
            notes.append("its hand weapon (the build cannot lend its look)")
        elif m and m.group(1) in (frame.get("animations") or {}):
            gone = m.group(1)
            del frame["animations"][gone]
            # back to the plain starter's move for that button (its own clip)
            for slot, ab in frame["abilities"].items():
                if ab.get("clip") == f"anim:{gone}":
                    ab["clip"] = start_clips.get(slot, "")
                for st in ab.get("combo") or []:
                    if st["clip"] == f"anim:{gone}":
                        st["clip"] = ""
                if ab.get("combo"):
                    ab["combo"] = [st for st in ab["combo"] if st["clip"]]
            notes.append(f"the move {gone} (it does not fit the body's skeleton)")
        elif frame.get("weapon"):
            # A lent weapon can fail as wiring that never names it.
            del frame["weapon"]
            notes.append("its hand weapon (the build refused it)")
        else:
            notes.append(f"build: {err}")
            return
    notes.append("build: still refused after several fixes; press Build check to see why")
