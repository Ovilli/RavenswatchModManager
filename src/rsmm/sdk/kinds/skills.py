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


def _text_key_base(source: str) -> str:
    """``Attack Dive`` / ``Skill_Attack_Dive`` -> ``Skill_Attack_Dive``."""
    s = source.strip()
    if s.lower().startswith("skill controller "):
        s = s[len("skill controller "):]
    if s.lower().startswith("skill_"):
        return s
    return "Skill_" + s.replace(" ", "_")


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
    decoded = f"Text/Hero_{hero_token}_Common~GAM.xls.LocalText.gen"
    enc = load_asset_map().get(decoded)
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
    key_base = _text_key_base(source)
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


def _emit_herodef(hero_token: str, defn: ContentDef, mode: str,
                  out_dir: Path) -> list[Path]:
    """Clone (net-new) or repoint (remint identity) a herodef skill row."""
    herodef = _HERODEF_DIR / f"{hero_token}.herodef.ot.DtHeroDefinition.gen"
    blob = herodef.read_bytes()
    source = defn.fields["source"]
    new_name = defn.fields.get("name") or defn.fields.get("display_name") or defn.id
    guid = _parse_guid(defn.fields.get("guid"))
    try:
        if mode == "clone":
            out, ident = SC.clone_skill(blob, source, new_name, new_guid1=guid)
        else:  # repoint: remint identity in place, keep the controller name
            out = SC.repoint_skill(blob, source, source, new_guid1=guid)
            row = SC.find_skill(out, source)
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
    if mode == "clone":
        # DISABLED — proven 2026-06-15 (TWICE): splicing a row into the herodef
        # makes the hero fail to load and vanish from selection. Tested with a
        # reminted GUID AND with the source GUID kept — both brick, so it is NOT
        # the identity: the skill collection is structurally validated in a way a
        # byte-splice violates (a count/length the deserialiser enforces, in the
        # registrar region Ghidra leaves unanalysed). Net-new skills are not
        # feasible by row insertion until that format is RE'd. Use mode="relabel"
        # (override an existing skill's text — visible & safe). See
        # docs/_re/kinds/skills-system.md.
        raise ContentError(
            f"skill {defn.id}: mode='clone' is DISABLED — inserting a skill row "
            f"bricks the hero (proven in-game, GUID-independent). Use "
            f"mode='relabel' to repurpose an existing skill instead.")
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
        written += _emit_text_override(hero_token, source, display_name,
                                       description, out_dir)
    else:  # relabel — override the source skill's text in place
        written += _emit_text_override(hero_token, source, display_name,
                                       description, out_dir)
    if not written:
        raise ContentError(
            f"skill {defn.id}: nothing to emit — give a name/description to "
            f"relabel, or mode=clone/repoint to edit the herodef.")
    _log.info("skill %s/%s: %s on %s (%d file(s))",
              mod_id, defn.id, mode, hero_token, len(written))
    return written
