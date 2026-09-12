"""Hero **skill** (talent) content builder — SDK entry point.

A hero's skills are the talents shown on the level-up cards and in the hero Skill
Menu. Two layers cooperate:

* **Display** — the visible name/description come from the per-hero text bank
  ``Text/Hero_<Hero>_Common~GAM.xls.LocalText.gen`` under keys
  ``Skill_<Suffix>_Name`` / ``_Desc`` (derived from the skill's controller name,
  spaces → underscores). Overriding those VALUES relabels an existing skill in
  the menu — reliable and count-neutral, the way to make a "custom talent" the
  player can actually see.
* **Identity / list** — the skill rows live in the herodef
  ``Definitions/Heroes/<Hero>.herodef.ot.DtHeroDefinition.gen`` (see
  :mod:`rsmm.engine.skill_clone`). Cloning a row adds a NET-NEW slot, but the
  in-game load of an added row is unproven (``guess``), and a clone inherits the
  source's display until a new text key + binding are authored.

So ``emit()`` makes the talent VISIBLE by default (text override) and, when
asked, also edits the herodef.

Fields:
    ``hero`` (str, required)         hero name, e.g. ``Aladdin`` / ``Snow_Queen``.
    ``source`` (str, required)       an existing skill to relabel/clone, by its
                                     controller suffix (``Attack Dive``) or text
                                     key base (``Skill_Attack_Dive``).
    ``name`` / ``display_name``      the talent name shown in-game (overrides
                                     ``Skill_<suffix>_Name``).
    ``description``                  the talent description (``_Desc``).
    ``mode`` (str, optional)         ``relabel`` (default — text only, visible &
                                     safe), ``clone`` (also add a NET-NEW herodef
                                     row, EXPERIMENTAL), or ``repoint`` (remint
                                     the source row's identity in place).
    ``guid`` (str, optional)         16-byte identity GUID for clone/repoint.
    ``controller`` (str, optional)   ``repoint`` only — rename the row's
                                     controller, e.g. ``Primary Finisher``. The
                                     display key and the Book column both derive
                                     from this name (``Primary`` -> Power), so
                                     renaming moves the slot AND retargets
                                     ``name``/``description`` at the new key.
                                     Point it at a controller that already
                                     exists in the hero ENTITY, and pass that
                                     controller's identity ``guid``, to adopt a
                                     built-but-unrostered talent.
    ``icon`` (str, optional)         a PNG shipped in the mod (path relative to
                                     the mod root). Cooked into an oCTexture and
                                     written OVER the slot's own icon texture,
                                     scaled to that texture's size. The slot's
                                     icon is found in the hero entity: the first
                                     ``.png`` path after the controller's name
                                     (28/28 on Red). In-place, so nothing needs
                                     registering.

Bind custom BEHAVIOUR with ``R.talent.on_pick`` / ``R.talent.define{hero=...}``.
See ``docs/_re/kinds/skills-system.md``.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path

from ...engine import skill_clone as SC
from ...engine import text_patches as TP
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

_HERODEF_DIR = DATA_DIR / "uncooked" / "Definitions" / "Heroes"
_ASSET_PREFIX = "Definitions/Heroes"


def _hero_token(hero: str) -> str | None:
    """Canonical herodef stem for a hero name (e.g. ``Snow_Queen``)."""
    if not _HERODEF_DIR.is_dir():
        return None
    low = hero.lower().replace(" ", "_")
    for p in _HERODEF_DIR.glob("*.herodef.ot.DtHeroDefinition.gen"):
        stem = p.name.split(".", 1)[0]
        if stem.lower() == low:
            return stem
    return None


#: Controller-name prefix -> text-key prefix. A hero's rows are named after the
#: INPUT SLOT (Red: ``Skill Controller Primary Bleed``) while its text keys are
#: named after the ABILITY (``Skill_Power_Bleed_Name``). Heroes that name rows
#: after the ability already — Aladdin's ``Attack Dive`` -> ``Skill_Attack_Dive``
#: — need no alias, which is why this stayed invisible until a hero that uses
#: the other convention was touched.
_KEY_PREFIX_ALIASES = {
    "Basic": "Attack",
    "Primary": "Power",
    "Secondary": "Special",
    "Defensive": "Defense",
}


def _key_base_candidates(source: str) -> list[str]:
    """Text-key bases ``source`` could mean, best guess first."""
    s = source.strip()
    if s.lower().startswith("skill controller "):
        s = s[len("skill controller "):]
    if s.lower().startswith("skill_"):
        return [s]
    out = ["Skill_" + s.replace(" ", "_")]
    head, _, tail = s.partition(" ")
    alias = _KEY_PREFIX_ALIASES.get(head)
    if alias and tail:
        out.append("Skill_" + f"{alias} {tail}".replace(" ", "_"))
    return out


def _text_key_base(source: str, bank_keys: list[str] | None = None) -> str:
    """``Attack Dive`` -> ``Skill_Attack_Dive``; ``Primary Bleed`` ->
    ``Skill_Power_Bleed`` when the bank says so.

    With ``bank_keys`` the answer is CHECKED against the hero's actual keys
    rather than assumed, so a wrong guess fails naming what it looked for.
    """
    cands = _key_base_candidates(source)
    if bank_keys is None:
        return cands[0]
    for c in cands:
        if f"{c}_Name" in bank_keys or f"{c}_Desc" in bank_keys:
            return c
    raise ContentError(
        f"skill: no text key for {source!r} — tried "
        + ", ".join(f"{c}_Name" for c in cands)
        + ". Check the controller name against the hero's bank.")


def _install_bank(hero_token: str):
    """Return ``(install_base_gen, decoded_path)`` for a hero's Common text bank
    in the live game install, or ``None`` when no install is reachable."""
    try:
        from rsmm.cli.apply_mods import COOKING_REL, find_game_dir, load_asset_map
    except ImportError:
        return None
    game = find_game_dir()
    if game is None:
        return None
    # apply-layer asset map is decoded->encoded with forward-slash keys.
    amap = load_asset_map()
    decoded = f"Text/Hero_{hero_token}_Common~GAM.xls.LocalText.gen"
    enc = amap.get(decoded)
    if not enc:
        # The bank token is not always the herodef stem's spelling: Red's
        # herodef is `Red.herodef...` but its bank is `Hero_RED_Common`. Fall
        # back to a case-insensitive match rather than reporting the hero has
        # no text at all.
        low = decoded.lower()
        for k, v in amap.items():
            if k.lower() == low:
                decoded, enc = k, v
                break
    if not enc:
        return None
    p = game / COOKING_REL / Path(*enc.split("\\"))
    return (p, decoded) if p.exists() else None


def _parse_guid(raw) -> bytes | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if ":" in s:
        lo, hi = s.split(":", 1)
        return struct.pack("<QQ", int(lo, 16), int(hi, 16))
    b = bytes.fromhex(s.removeprefix("0x"))
    if len(b) != 16:
        raise ContentError(f"skill guid must be 16 bytes, got {len(b)}")
    return b


def _write_bank_files(decoded_bank: str, files: dict[str, bytes],
                      out_dir: Path) -> list[Path]:
    """Write a bank-patch result ({token -> bytes}) into the mod assets.

    ``token`` is ``.Lang<XX>`` for a language sibling, or ``__base__`` for the
    keys file (only produced by an APPEND, where keys change)."""
    written: list[Path] = []
    for token, blob in files.items():
        decoded = decoded_bank if token == "__base__" else f"{decoded_bank}{token}"
        dest = out_dir / Path(*decoded.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)
    return written


def _emit_text_override(hero_token: str, source: str, display_name, description,
                        out_dir: Path) -> list[Path]:
    """Relabel an existing skill by overriding its bank text VALUES (the source
    keys must already exist). Count-neutral. Empty if no text requested."""
    if display_name is None and description is None:
        return []
    base_gen, decoded_bank = _require_bank(hero_token)
    key_base = _text_key_base(source, TP.parse_text_file(base_gen).entries)
    overrides: dict[str, str] = {}
    if display_name is not None:
        overrides[f"{key_base}_Name"] = str(display_name)
    if description is not None:
        overrides[f"{key_base}_Desc"] = str(description)
    try:
        files = TP.override_bank_values(base_gen, overrides)
    except KeyError as e:
        raise ContentError(str(e)) from e
    return _write_bank_files(decoded_bank, files, out_dir)


def _emit_text_append(hero_token: str, new_name: str, display_name, description,
                      out_dir: Path) -> list[Path]:
    """Append a NEW text key for a cloned skill's controller name, so the new
    row has its own display string (vs inheriting the source's)."""
    base_gen, decoded_bank = _require_bank(hero_token)
    key_base = _text_key_base(new_name)
    pairs = {f"{key_base}_Name": str(display_name) if display_name is not None
             else new_name}
    if description is not None:
        pairs[f"{key_base}_Desc"] = str(description)
    files = TP.append_bank_keys(base_gen, pairs)
    return _write_bank_files(decoded_bank, files, out_dir)


def _require_bank(hero_token: str) -> tuple[Path, str]:
    bank = _install_bank(hero_token)
    if bank is None:
        raise ContentError(
            f"skill: no install text bank for {hero_token!r} reachable — run "
            f"apply against a Ravenswatch install so the display name can be set.")
    return bank


_ENTITY_DIR = DATA_DIR / "uncooked" / "EntitySettings" / "Heroes"
_UI_MIRROR = DATA_DIR / "uncooked"


def _slot_icon_texture(hero_token: str, controller: str) -> str:
    """Decoded path of the icon texture a skill slot draws, e.g.
    ``Ui/Heroes/Red/Skill Special Quick Bombs.png.Texture.dxt``.

    The controller node in the hero ENTITY carries its icon as a plain resource
    path a few hundred bytes after its name; that path plus ``Ui/`` and the
    texture suffix is the cooked asset. Resolved from the entity rather than
    guessed from the name, because icon file names do not follow the controller
    name (Red's ``Secondary Quick Bombs`` draws ``Skill Special Quick Bombs``).
    """
    from ...engine import talent_values as TV

    name = controller.strip()
    if not name.lower().startswith("skill controller "):
        name = f"Skill Controller {name}"
    pat = struct.pack("<I", len(name)) + name.encode("ascii")
    low = hero_token.lower()
    dirs = [d for d in _ENTITY_DIR.glob("Hero_*") if d.name[5:].lower() == low]
    for d in dirs:
        for gen in sorted(d.glob("*.entity.ot.EntitySettingsResource.gen")):
            blob = gen.read_bytes()
            at = blob.find(pat)
            if at < 0:
                continue
            for _off, text in TV._iter_lstrings(blob[at:at + 900]):
                if text.lower().endswith(".png"):
                    return "Ui/" + text.replace("\\", "/") + ".Texture.dxt"
    raise ContentError(
        f"skill: no icon found for {name!r} in {hero_token}'s entity files")


def _scale_rgba(w: int, h: int, rgba: bytes, nw: int, nh: int) -> bytes:
    """Area-average resample, alpha-premultiplied so transparent edges do not
    bleed dark fringes into the icon. Stdlib only: the runtime CLI declares no
    dependencies, so Pillow is not available to a user's install."""
    out = bytearray(nw * nh * 4)
    sx, sy = w / nw, h / nh
    for y in range(nh):
        y0, y1 = int(y * sy), max(int(y * sy) + 1, int((y + 1) * sy))
        for x in range(nw):
            x0, x1 = int(x * sx), max(int(x * sx) + 1, int((x + 1) * sx))
            r = g = b = a = n = 0
            for yy in range(y0, min(y1, h)):
                row = yy * w
                for xx in range(x0, min(x1, w)):
                    i = (row + xx) * 4
                    pa = rgba[i + 3]
                    r += rgba[i] * pa
                    g += rgba[i + 1] * pa
                    b += rgba[i + 2] * pa
                    a += pa
                    n += 1
            o = (y * nw + x) * 4
            if a:
                out[o] = r // a
                out[o + 1] = g // a
                out[o + 2] = b // a
            out[o + 3] = a // n if n else 0
    return bytes(out)


def _emit_icon(hero_token: str, controller: str, icon: str,
               mod_root: Path, out_dir: Path) -> list[Path]:
    """Cook a mod PNG over the slot's own icon texture."""
    from ...engine import image as IMG
    from ...engine.cooked_schemas.texture import TextureHandler

    src = mod_root / icon
    if not src.is_file() or src.suffix.lower() != ".png":
        raise ContentError(f"skill: icon {icon!r} is not a PNG in the mod ({src})")
    decoded = _slot_icon_texture(hero_token, controller)
    png = src.read_bytes()
    w, h, rgba = IMG.decode_png(png)
    # Match the vanilla texture's size when the mirror has it, so the cooked
    # icon occupies the same memory and layout as the one it replaces.
    mirror = _UI_MIRROR / decoded.removesuffix(".Texture.dxt")
    if mirror.is_file():
        vw, vh, _ = IMG.decode_png(mirror.read_bytes())
        if (vw, vh) != (w, h):
            rgba, w, h = _scale_rgba(w, h, rgba, vw, vh), vw, vh
            png = IMG.encode_png(w, h, rgba)
    cooked = TextureHandler().encode_container(png)
    dest = out_dir / Path(*decoded.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(cooked)
    _log.info("skill: icon %s -> %s (%dx%d)", icon, decoded, w, h)
    return [dest]


def _emit_herodef(hero_token: str, defn: ContentDef, mode: str,
                  out_dir: Path) -> list[Path]:
    """Clone (net-new) or repoint (remint identity) a herodef skill row."""
    herodef = _HERODEF_DIR / f"{hero_token}.herodef.ot.DtHeroDefinition.gen"
    blob = herodef.read_bytes()
    source = defn.fields["source"]
    new_name = defn.fields.get("name") or defn.fields.get("display_name") or defn.id
    guid = _parse_guid(defn.fields.get("guid"))
    # Whether the clone gets a FRESH identity GUID.
    #
    # `clone_skill` defaults to keeping the source's, on the reasoning that a
    # reminted-but-unresolvable GUID broke a cloned magical object. That case
    # was a resource REFERENCE. A skill row's +0x10 GUID is an identity DEDUP
    # KEY, and playtest 1 (2026-09-11) crashed in HeroDef_PostLoad walking a
    # per-skill sub-vector through a poison pointer — the shape you get when a
    # dedup path sees two rows claiming one identity and drops one of them.
    remint = bool(defn.fields.get("remint"))
    try:
        if mode == "clone":
            out, ident = SC.clone_skill(blob, source, new_name,
                                        new_guid1=guid, remint=remint)
        else:  # repoint: rewrite the row in place, keeping the slot count
            # `controller` renames the row; without it the name is kept and
            # only the identity GUID moves.
            target = str(defn.fields.get("controller") or source)
            out = SC.repoint_skill(blob, source, target, new_guid1=guid)
            row = SC.find_skill(out, target)
            ident = guid if guid is not None else out[row.guid1_off:row.guid1_off + 16]
    except SC.SkillCloneError as e:
        raise ContentError(f"skill {defn.id}: {e}") from e
    lo, hi = struct.unpack("<QQ", ident)
    _log.info("skill %s: herodef %s on %s — identity 0x%x:0x%x (bind with "
              "R.talent.on_pick)", defn.id, mode, hero_token, lo, hi)
    decoded = f"{_ASSET_PREFIX}/{herodef.name}"
    dest = out_dir / Path(*decoded.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out)
    return [dest]


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one skill def into the mod's ``assets/`` tree."""
    C.validate_id("skill", defn.id)
    hero = defn.fields.get("hero")
    source = defn.fields.get("source")
    if not hero or not isinstance(hero, str):
        raise SchemaNotMined(f"skill {defn.id}: needs a 'hero' name (e.g. Aladdin).")
    if not source or not isinstance(source, str):
        raise ContentError(f"skill {defn.id}: needs a 'source' skill (e.g. 'Attack Dive').")
    hero_token = _hero_token(hero)
    if hero_token is None:
        raise ContentError(
            f"skill {defn.id}: no herodef for {hero!r} under Definitions/Heroes "
            f"(is data/uncooked present?)")

    mode = (defn.fields.get("mode") or "relabel").lower()
    if mode not in ("relabel", "clone", "repoint"):
        raise ContentError(f"skill {defn.id}: mode must be relabel/clone/repoint.")
    if defn.fields.get("controller") and mode != "repoint":
        raise ContentError(
            f"skill {defn.id}: 'controller' renames a herodef row, so it only "
            f"applies to mode='repoint' (got {mode!r}).")
    if mode == "clone" and not defn.fields.get("accept_brick_risk"):
        # GATED, no longer blanket-disabled.
        #
        # It WAS disabled on the reading that the deserialiser enforces "a
        # count/length in the registrar region Ghidra leaves unanalysed". That
        # reason is superseded: the count is a plain u32 in a class-index table
        # immediately before the rows, and nothing was writing it — see
        # skill_clone.grow_class_table, which clone_skill now calls. A spliced
        # row was an ORPHAN, the same bug already fixed for entities and levels.
        #
        # The gate stays because the fix is proven OFFLINE ONLY. The failure it
        # guards against is not subtle: the previous attempt removed Aladdin
        # from the hero-selection menu entirely. Opting in is therefore explicit
        # and per-def, and the flag name says what you are accepting.
        #
        # ⚠ Even when this loads, the talent may not be VISIBLE. The Book grid
        # derives a cell from skill identity and does not enumerate by vector
        # length, so a clone that inherits its source's identity draws on top of
        # it. That wall is separate from this one and untested — see
        # docs/_re/kinds/skills-system.md.
        raise ContentError(
            f"skill {defn.id}: mode='clone' needs `accept_brick_risk = true`. "
            f"The herodef count bug behind the old block is fixed "
            f"(skill_clone.grow_class_table) but PROVEN OFFLINE ONLY, and a bad "
            f"row removes the hero from the selection menu. Back up "
            f"Definitions/Heroes/<Hero>.herodef.ot.DtHeroDefinition.gen first.")
    display_name = defn.fields.get("display_name") or defn.fields.get("name")
    description = defn.fields.get("description")

    written: list[Path] = []
    if mode == "clone":
        # NET-NEW skill: keep the source, add a new herodef row (new identity)
        # and APPEND its own text key so it doesn't inherit the source's name.
        written += _emit_herodef(hero_token, defn, mode, out_dir)
        new_name = str(display_name or defn.id)
        written += _emit_text_append(hero_token, new_name, display_name,
                                     description, out_dir)
    elif mode == "repoint":
        written += _emit_herodef(hero_token, defn, mode, out_dir)
        # A renamed row reads its display text from the NEW controller's keys.
        written += _emit_text_override(hero_token,
                                       str(defn.fields.get("controller") or source),
                                       display_name, description, out_dir)
    else:  # relabel — override the source skill's text in place
        written += _emit_text_override(hero_token, source, display_name,
                                       description, out_dir)
    icon = defn.fields.get("icon")
    if icon:
        slot = str(defn.fields.get("controller") or source) if mode == "repoint" else source
        written += _emit_icon(hero_token, slot, str(icon), out_dir.parent, out_dir)
    if not written:
        raise ContentError(
            f"skill {defn.id}: nothing to emit — give a name/description to "
            f"relabel, or mode=clone/repoint to edit the herodef.")
    _log.info("skill %s/%s: %s on %s (%d file(s))",
              mod_id, defn.id, mode, hero_token, len(written))
    return written
