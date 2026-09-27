"""The Items and Talents tabs: shipped content in, manifest blocks out.

* **Items** — pick a shipped magical object as the base, give the copy an id,
  name, description, rarity and icon, change any of its values, and switch
  which stat each effect / super effect changes (with super effect text to
  match). Emits one ``kind = "item"`` block.
* **Talents** — pick a hero, change any talent value in any of its entity
  files, and rename or re-describe its talent cards. Emits one
  ``kind = "talent"`` block per edited file and one ``kind = "skill"`` block
  per edited card.

Nothing here writes game files. **Check** runs the real kind builders into a
temp dir, so the page reports exactly what ``rsmm apply`` would refuse, and
**Add to mod** appends the blocks to a mod's ``manifest.toml`` (or creates the
mod). The page is ``pages/content.html``; routing is ``editor.app``.
"""

from __future__ import annotations

import json
import re
import tempfile
import tomllib
from functools import cache
from pathlib import Path

from rsmm.cli.editor.app import Fail, Raw, Request

MOUNT = "content"
PAGE = "content.html"

_HEROES_DIR = "EntitySettings/Heroes"
_GEN_SUFFIX = ".entity.ot.EntitySettingsResource.gen"
_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
_MOD_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_STEM_RE = re.compile(r"^[A-Za-z0-9_]+$")


class EditorError(ValueError):
    """A request the page can show to the user as it is."""


# --- items ------------------------------------------------------------------

@cache
def items() -> list[dict]:
    """Every shipped magical object, with its display name when an install is
    readable (the names live in the install's text bank)."""
    from rsmm.cli.cmd_items import _iter_items
    from rsmm.engine import item_catalog

    names = {i.id: i for i in item_catalog.catalog()}
    out = []
    for item_id, rarity, _p in _iter_items():
        info = names.get(item_id)
        out.append({"id": item_id, "rarity": rarity,
                    "name": (info.name if info else None) or item_id,
                    "description": (info.description if info else None) or "",
                    "icon": _icon_stem(info.icon if info else None)})
    out.sort(key=lambda i: (i["rarity"], i["name"].lower()))
    return out


def _icon_stem(icon: str | None) -> str | None:
    """``Objects\\Icon_Object_Dreamcatcher.png`` -> ``Icon_Object_Dreamcatcher``."""
    from rsmm.engine.item_catalog import _icon_stem as stem
    return stem(icon)


def item_detail(item_id: str) -> dict:
    """What the form needs for one base item: its values and their state."""
    from rsmm.cli.cmd_items import _find_item
    from rsmm.engine import magic_item_cook as cook
    from rsmm.engine.talent_values import list_talent_values

    found = _find_item(item_id)
    if found is None:
        raise EditorError(f"no shipped item {item_id!r}")
    _id, rarity, p = found
    data = p.read_bytes()
    from rsmm.engine import item_modifier as IM

    shadowed = {tv.label for tv in list_talent_values(data) if tv.is_overridden}
    meta = next((i for i in items() if i["id"] == _id), {})
    super_key = IM.super_text_key(data)
    return {
        "id": _id, "rarity": rarity,
        "name": meta.get("name") or _id, "description": meta.get("description") or "",
        "icon": _icon_stem(cook.find_icon(data)),
        "idBytes": len(_id.encode("utf-8")),
        "values": [{"label": label, "value": value, "shadowed": label in shadowed}
                   for label, value in cook.list_value_fields(data)],
        "modifiers": [{"name": m.name, "stat": m.stat or _hex(m.key), "named": m.stat is not None,
                       "super": m.super_effect} for m in IM.list_modifiers(data)],
        "superKey": super_key,
        "superText": (_text_values().get(super_key) or "") if super_key else "",
    }


def _hex(key: int) -> str:
    return f"0x{key:08x}"


@cache
def _text_values() -> dict[str, str]:
    """The install's magical-object text bank, key -> English text."""
    from rsmm.cli.apply_mods import find_game_dir, load_asset_map
    from rsmm.engine import item_catalog
    game = find_game_dir()
    if game is None:
        return {}
    return item_catalog._text_values(game, load_asset_map())


def stats() -> list[str]:
    """Every stat a modifier can change, by the engine's own display name."""
    from rsmm.engine.item_modifier import stat_catalog
    return sorted(stat_catalog(), key=str.lower)


@cache
def icon_stems() -> list[str]:
    """Every icon under ``Ui/Objects`` by its full leaf name. Items use
    ``Icon_Object_*`` and ``Icon_PowerUp_*`` as well as ``UI_Object_*``."""
    from rsmm.engine import corpus
    return sorted({rel.rsplit("/", 1)[-1].split(".png", 1)[0]
                   for rel in corpus.rels("Ui/Objects/") if ".png" in rel})


def icon_png(stem: str) -> bytes | None:
    """A shipped item icon as PNG, by stem (``GreenArmor``)."""
    from rsmm.cli.apply_mods import find_game_dir
    from rsmm.engine import item_catalog

    if not _STEM_RE.match(stem):
        return None
    game = find_game_dir()
    if game is None:
        return None
    info = item_catalog.ItemInfo(id=stem, rarity="", name=None, description=None,
                                 icon=f"Objects\\{stem}.png")
    return item_catalog.icon_png(game, info)


# --- talents ----------------------------------------------------------------

@cache
def _herodefs() -> dict[str, str]:
    """Hero folder name (``SunWukong``) -> herodef stem (``Sun_Wukong``).

    The two spellings differ for some heroes; a folder with no herodef
    (``Pets``, the unreleased ``Alice``) is not a playable hero."""
    from rsmm.engine import corpus
    from rsmm.sdk.kinds import skills as S

    defs = {s.replace("_", "").lower(): s
            for s in corpus.stems(S._HERODEF_DIR, S._HERODEF_SUFFIX)}
    out = {}
    for d in corpus.subdirs(_HEROES_DIR):
        name = d.removeprefix("Hero_")
        token = defs.get(name.replace("_", "").lower())
        if d.startswith("Hero_") and token:
            out[name] = token
    return out


def heroes() -> list[str]:
    """Playable shipped heroes, by folder name without ``Hero_``."""
    return sorted(_herodefs())


def _hero_dir(hero: str) -> str:
    if hero not in heroes():
        raise EditorError(f"no shipped hero {hero!r}")
    return f"Hero_{hero}"


@cache
def talent_values(hero: str) -> list[dict]:
    """Every editable talent value of ``hero``, grouped by entity file.

    Spawner/runtime values are left out: writing one changes nothing in game.
    A label that appears twice in one file is listed once, because a patch
    names a label and lands on its first occurrence."""
    from rsmm.engine import corpus
    from rsmm.engine.talent_values import TYPE_BOOL, list_talent_values

    files = []
    for p in corpus.files(f"{_HEROES_DIR}/{_hero_dir(hero)}", _GEN_SUFFIX):
        seen: set[str] = set()
        rows = []
        for v in list_talent_values(p.read_bytes()):
            if v.is_spawner or v.label in seen:
                continue
            seen.add(v.label)
            kind = "bool" if v.type_code == TYPE_BOOL else "int" if v.is_int else "float"
            value = bool(v.value) if kind == "bool" else int(v.value) if kind == "int" \
                else v.value
            rows.append({"label": v.label, "value": value, "type": kind,
                         "shadowed": v.is_overridden})
        if rows:
            files.append({"file": p.name.split(".entity.ot.", 1)[0], "values": rows})
    return files


@cache
def talent_cards(hero: str) -> list[dict]:
    """The hero's talent cards with their current English name and text.

    A card is a ``Skill Controller <X>`` in the hero's main entity whose text
    key the hero's bank really holds; controllers with no text (helpers such
    as ``Attack Controller Burst``) are not cards and are left out."""
    from rsmm.engine import corpus
    from rsmm.engine import skill_clone as SC
    from rsmm.engine import text_patches as TP
    from rsmm.sdk.content import ContentError
    from rsmm.sdk.kinds import skills as S

    folder = _hero_dir(hero)
    main = corpus.read(f"{_HEROES_DIR}/{folder}/{folder}{_GEN_SUFFIX}")
    bank = S._install_bank(_herodefs()[hero])
    if main is None or bank is None:
        return []
    keys = TP.parse_text_file(bank[0]).entries
    try:
        vals = TP.parse_text_file(TP.lang_path_for(bank[0], "EN")).entries
    except (OSError, ValueError):
        vals = []
    text = dict(zip(keys, vals, strict=False))
    out = []
    for source in sorted({n[len("Skill Controller "):]
                          for _o, n in SC._iter_name_offsets(main)}):
        try:
            base = S._text_key_base(source, keys)
        except ContentError:
            continue
        name_key, desc_key = S.card_keys(base, keys)
        out.append({"source": source,
                    "name": (text.get(name_key) or "").strip() if name_key else "",
                    "description": text.get(desc_key) or "" if desc_key else "",
                    "hasName": name_key is not None, "hasDescription": desc_key is not None})
    return out


# --- manifest blocks ----------------------------------------------------------

def _toml(value) -> str:
    """One TOML value. Strings go through JSON, whose escapes TOML shares."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_toml(str(k))} = {_toml(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"no TOML form for {value!r}")


def _block(fields: dict) -> str:
    width = max(len(k) for k in fields)
    lines = ["[[content]]"]
    for k, v in fields.items():
        if k == "value_patches" and len(v) > 1:
            lines.append(f"{k:<{width}} = [")
            lines += [f"    {_toml(p)}," for p in v]
            lines.append("]")
        else:
            lines.append(f"{k:<{width}} = {_toml(v)}")
    return "\n".join(lines)


def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise EditorError(f"{what}: {v!r} is not a number")
    return v


def item_defs(req: dict) -> list[tuple[str, str, dict]]:
    """``(kind, id, fields)`` for an item request, validated.

    ``req``: ``id``, ``base``, optional ``name``/``description``/``rarity``/
    ``icon``, ``values`` = ``[{label, old, new, shadowed}]`` (changed only),
    ``stats`` = ``[{modifier, stat}]`` (changed only) and ``superDescription``.
    """
    base, new_id = str(req.get("base") or ""), str(req.get("id") or "")
    if not base:
        raise EditorError("pick a base item")
    if not _ID_RE.match(new_id):
        raise EditorError("the id takes letters, digits and _ only")
    if len(new_id.encode()) != len(base.encode()):
        raise EditorError(
            f"the id must be exactly as long as the base's ({len(base)} characters, "
            f"now {len(new_id)}): the item copy keeps every byte offset")
    if new_id == base:
        raise EditorError("give the copy an id of its own")
    fields: dict = {"kind": "item", "id": new_id, "base": base}
    for key in ("name", "description", "rarity"):
        v = req.get(key)
        if isinstance(v, str) and v.strip():
            fields[key] = v.strip() if key != "description" else v
    icon = req.get("icon")
    if isinstance(icon, str) and icon.strip():
        icon = icon.strip()
        if not _STEM_RE.match(icon):
            raise EditorError(f"no icon {icon!r}")
        # The full path: a bare stem would be read as `UI_Object_<stem>`.
        fields["icon"] = f"Objects\\{icon}.png"
    patches = []
    for row in req.get("values") or []:
        label = str(row.get("label") or "")
        old, new = _num(row.get("old"), label), _num(row.get("new"), label)
        if not label or old == new:
            continue
        patches.append([label, float(old), float(new), *([True] if row.get("shadowed")
                                                        else [])])
    if patches:
        fields["value_patches"] = patches
    from rsmm.engine.item_modifier import ItemModifierError, resolve_stat
    swaps = {}
    for row in req.get("stats") or []:
        modifier, stat = str(row.get("modifier") or ""), str(row.get("stat") or "")
        if not modifier or not stat:
            continue
        try:
            resolve_stat(stat)
        except ItemModifierError as e:
            raise EditorError(f"{modifier}: {e}") from None
        swaps[modifier] = stat
    if swaps:
        fields["stats"] = swaps
    sup = req.get("superDescription")
    if isinstance(sup, str) and sup.strip():
        fields["super_description"] = sup
    return [("item", new_id, fields)]


def talent_defs(req: dict) -> list[tuple[str, str, dict]]:
    """``(kind, id, fields)`` for a talent request, validated.

    ``req``: ``hero``, ``prefix`` (the block-id stem), ``values`` =
    ``[{file, label, type, old, new, shadowed}]`` and ``cards`` =
    ``[{source, name?, description?}]``; only changed rows are sent."""
    hero = str(req.get("hero") or "")
    prefix = str(req.get("prefix") or "")
    if not hero:
        raise EditorError("pick a hero")
    if not _ID_RE.match(prefix):
        raise EditorError("the block id takes letters, digits and _ only")
    by_file: dict[str, list] = {}
    for row in req.get("values") or []:
        file, label, kind = str(row.get("file") or ""), str(row.get("label") or ""), \
            row.get("type")
        if not file or not label:
            raise EditorError("a value row needs its file and label")
        if kind == "bool":
            old, new = bool(row.get("old")), bool(row.get("new"))
        elif kind == "int":
            old, new = _num(row.get("old"), label), _num(row.get("new"), label)
            if new != int(new):
                raise EditorError(f"{label}: a whole number, not {new}")
            old, new = int(old), int(new)
        else:
            old, new = float(_num(row.get("old"), label)), float(_num(row.get("new"), label))
        if old == new:
            continue
        by_file.setdefault(file, []).append(
            [label, old, new, *([True] if row.get("shadowed") else [])])
    out: list[tuple[str, str, dict]] = []
    for file, patches in by_file.items():
        slug = re.sub(r"[^A-Za-z0-9_]", "_", file.removeprefix(f"Hero_{hero}"))
        tid = f"{prefix}{slug}" if slug else prefix
        out.append(("talent", tid, {"kind": "talent", "id": tid, "hero": hero,
                                    "file": f"{file}.entity", "value_patches": patches}))
    for card in req.get("cards") or []:
        source = str(card.get("source") or "")
        if not source:
            raise EditorError("a card needs its source")
        fields: dict = {}
        for key in ("name", "description"):
            v = card.get(key)
            if isinstance(v, str) and v.strip():
                fields[key] = v
        if not fields:
            continue
        sid = f"{prefix}_{re.sub(r'[^A-Za-z0-9_]', '_', source)}"
        # The skill kind names a hero by its herodef (``Sun_Wukong``), the
        # talent kind by its folder (``SunWukong``).
        out.append(("skill", sid, {"kind": "skill", "id": sid,
                                   "hero": _herodefs().get(hero, hero),
                                   "source": source, **fields}))
    if not out:
        raise EditorError("nothing changed yet")
    return out


def defs_for(tab: str, req: dict) -> list[tuple[str, str, dict]]:
    if tab == "items":
        return item_defs(req)
    if tab == "talents":
        return talent_defs(req)
    raise EditorError(f"unknown tab {tab!r}")


def to_toml(defs: list[tuple[str, str, dict]]) -> str:
    return "\n\n".join(_block(f) for _k, _i, f in defs) + "\n"


def check(defs: list[tuple[str, str, dict]]) -> list[dict]:
    """Build each block with its real kind into a temp dir: the same code
    ``rsmm apply`` runs, so its refusals are the ones apply would give."""
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import items as K_items
    from rsmm.sdk.kinds import skills as K_skills
    from rsmm.sdk.kinds import talents as K_talents

    builders = {"item": K_items.emit, "talent": K_talents.emit, "skill": K_skills.emit}
    out = []
    with tempfile.TemporaryDirectory(prefix="rsmm-editor-") as tmp:
        for i, (kind, cid, fields) in enumerate(defs):
            assets = Path(tmp) / str(i) / "assets"
            assets.mkdir(parents=True)
            body = {k: v for k, v in fields.items() if k not in ("kind", "id")}
            try:
                written = builders[kind]("editor_check", ContentDef(kind, cid, body), assets)
            except (ValueError, KeyError, NotImplementedError, OSError) as e:
                out.append({"id": cid, "kind": kind, "ok": False, "error": str(e)})
                continue
            out.append({"id": cid, "kind": kind, "ok": True, "files": len(written)})
    return out


# --- mods ---------------------------------------------------------------------

def list_mods(root: Path) -> list[dict]:
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        m = d / "manifest.toml"
        if d.name.startswith((".", "_")) or not m.is_file():
            continue
        try:
            mod = tomllib.loads(m.read_text(encoding="utf-8")).get("mod", {})
        except (OSError, tomllib.TOMLDecodeError):
            continue
        out.append({"id": d.name, "name": str(mod.get("name") or d.name)})
    return out


def _new_manifest(mod_id: str, name: str) -> str:
    from rsmm.sdk.manifest_spec import SCHEMA_URL
    return "\n".join([
        f"#:schema {SCHEMA_URL}", "", "[mod]",
        f"id          = {_toml(mod_id)}",
        f"name        = {_toml(name or mod_id)}",
        'version     = "0.1.0"',
        'author      = "you"',
        'description = ""',
        "enabled     = true",
        'sdk_version = ">=3.0,<4"',
        "tags        = []",
        'license     = ""',
    ]) + "\n"


def save(defs: list[tuple[str, str, dict]], mod_id: str, root: Path, *,
         create: bool = False, name: str = "") -> Path:
    """Append the blocks to ``mods/<mod_id>/manifest.toml`` (or create the mod).

    Refuses an id the manifest already uses for that kind, and puts the old
    text back if the result does not parse, so a manifest is never left
    half-written."""
    if not _MOD_ID_RE.match(mod_id):
        raise EditorError("a mod id takes letters, digits, - and _ only")
    target = root / mod_id
    manifest = target / "manifest.toml"
    if create:
        if target.exists():
            raise EditorError(f"a mod named {mod_id!r} already exists")
        (target / "assets").mkdir(parents=True)
        old = _new_manifest(mod_id, name)
    else:
        if not manifest.is_file():
            raise EditorError(f"no mod {mod_id!r} in {root}")
        old = manifest.read_text(encoding="utf-8")
    try:
        have = {(c.get("kind"), c.get("id"))
                for c in tomllib.loads(old).get("content", []) if isinstance(c, dict)}
    except tomllib.TOMLDecodeError as e:
        raise EditorError(f"{manifest} does not parse: {e}") from e
    clash = [f"{k} {i!r}" for k, i, _f in defs if (k, i) in have]
    if clash:
        raise EditorError(f"{mod_id} already has " + ", ".join(clash) + " — change the id")
    new = old.rstrip("\n") + "\n\n" + to_toml(defs)
    try:
        tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:          # pragma: no cover - _toml is strict
        raise EditorError(f"the result would not parse: {e}") from e
    manifest.write_text(new, encoding="utf-8")
    return manifest


# --- routes ---------------------------------------------------------------------

def _defs(req: Request) -> list[tuple[str, str, dict]]:
    edit = req.body.get("edit")
    if not isinstance(edit, dict):
        raise EditorError("the request needs an 'edit' object")
    return defs_for(str(req.body.get("tab") or ""), edit)


def _icon(req: Request) -> Raw:
    png = icon_png(req.arg("stem"))
    if png is None:
        raise Fail(404, "no such icon")
    return Raw(png, "image/png", cache=True)


def _save(req: Request) -> dict:
    defs = _defs(req)
    where = save(defs, str(req.body.get("mod") or ""), req.ctx.mods_dir,
                 create=bool(req.body.get("create")), name=str(req.body.get("name") or ""))
    return {"saved": str(where), "blocks": len(defs)}


ROUTES = {
    ("GET", "/api/items"): lambda req: {"items": items()},
    ("GET", "/api/item"): lambda req: item_detail(req.arg("id")),
    ("GET", "/api/icons"): lambda req: {"icons": icon_stems()},
    ("GET", "/api/stats"): lambda req: {"stats": stats()},
    ("GET", "/api/icon"): _icon,
    ("GET", "/api/heroes"): lambda req: {"heroes": heroes()},
    ("GET", "/api/talents"): lambda req: {"hero": req.arg("hero"),
                                          "files": talent_values(req.arg("hero")),
                                          "cards": talent_cards(req.arg("hero"))},
    ("GET", "/api/mods"): lambda req: {"mods": list_mods(req.ctx.mods_dir)},
    ("POST", "/api/toml"): lambda req: {"toml": to_toml(_defs(req))},
    ("POST", "/api/check"): lambda req: {"toml": to_toml(d := _defs(req)), "results": check(d)},
    ("POST", "/api/save"): _save,
}
