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

import base64
import binascii
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
        "card": _card(data),
    }


# The two texts a card shows under its name, by the String Format that holds them.
_CARD_FORMATS = {"description": "Descripton Format", "super": "Super Effect Descripton Format"}


def _card(data: bytes) -> dict:
    """The raw card texts (markup kept) and what fills each ``{N}`` of them."""
    from rsmm.engine import item_modifier as IM
    formats = IM.card_formats(data)
    text = _text_values()
    out = {}
    for part, fmt_name in _CARD_FORMATS.items():
        fmt = formats.get(fmt_name)
        if fmt is None:
            continue
        out[part] = {
            "key": fmt.key, "text": text.get(fmt.key) or "",
            "entries": [None if e is None else
                        {"node": e.node, "kind": e.kind, "sources": list(e.sources)}
                        for e in fmt.entries],
        }
    return out


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


@cache
def stats() -> list[dict]:
    """Every stat a modifier can change, by the engine's own display name, with
    how many shipped item effects give it (the picker lists those first)."""
    from rsmm.cli.cmd_items import _iter_items
    from rsmm.engine import item_modifier as IM

    used: dict[int, int] = {}
    for _id, _rarity, p in _iter_items():
        try:
            for m in IM.list_modifiers(p.read_bytes()):
                used[m.key] = used.get(m.key, 0) + 1
        except (OSError, ValueError):
            continue
    return [{"name": n, "used": used.get(k, 0)}
            for n, k in sorted(IM.stat_catalog().items(), key=lambda kv: kv[0].lower())]


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
    from rsmm.engine import item_modifier as IM
    from rsmm.engine.talent_values import TYPE_BOOL, list_talent_values

    files = []
    for p in corpus.files(f"{_HEROES_DIR}/{_hero_dir(hero)}", _GEN_SUFFIX):
        data = p.read_bytes()
        seen: set[str] = set()
        rows = []
        for v in list_talent_values(data):
            if v.is_spawner or v.label in seen:
                continue
            seen.add(v.label)
            kind = "bool" if v.type_code == TYPE_BOOL else "int" if v.is_int else "float"
            value = bool(v.value) if kind == "bool" else int(v.value) if kind == "int" \
                else v.value
            rows.append({"label": v.label, "value": value, "type": kind,
                         "shadowed": v.is_overridden})
        mods = [{"name": m.name, "stat": m.stat or _hex(m.key), "named": m.stat is not None,
                 "super": False} for m in IM.list_modifiers(data)]
        if rows or mods:
            files.append({"file": p.name.split(".entity.ot.", 1)[0], "values": rows,
                          "modifiers": mods})
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
    formats = _hero_formats(hero)
    labels = {(f["file"], v["label"]) for f in talent_values(hero) for v in f["values"]}
    out = []
    for source in sorted({n[len("Skill Controller "):]
                          for _o, n in SC._iter_name_offsets(main)}):
        try:
            base = S._text_key_base(source, keys)
        except ContentError:
            continue
        name_key, desc_key = S.card_keys(base, keys)
        file, fmt = formats.get(desc_key, (None, None))
        entries = [] if fmt is None else [
            None if e is None else {"node": e.node, "kind": e.kind, "sources": list(e.sources),
                                    **_tiers(hero, file, e)}
            for e in fmt.entries]
        # The values behind the card's {N}: a plain node itself, or what a
        # computed one is worked out from. Looked up in the text's own file.
        refs = []
        for e in entries:
            for label in ([e["node"]] if e and e["kind"] == "Value" else e["sources"] if e else []):
                if (file, label) in labels and {"file": file, "label": label} not in refs:
                    refs.append({"file": file, "label": label})
        icon = _card_icon(hero, source)
        out.append({"source": source,
                    "name": (text.get(name_key) or "").strip() if name_key else "",
                    "description": text.get(desc_key) or "" if desc_key else "",
                    "hasName": name_key is not None, "hasDescription": desc_key is not None,
                    "entries": entries, "file": file, "values": refs, "icon": icon})
    return out


def _tiers(hero: str, file: str, entry) -> dict:
    """``{"tiers": {tier: {index, value}}}`` when the placeholder is a per-rarity
    selector (most talent numbers are), else nothing."""
    if entry.kind != "Value Selector":
        return {}
    from rsmm.engine.talent_values import tier_values
    data = _hero_file(hero, file)
    tiers = tier_values(data, entry.node) if data else {}
    if not tiers:
        return {}
    return {"tiers": {t: {"index": i, "value": v} for t, (i, v, _tc) in tiers.items()}}


@cache
def _hero_file(hero: str, file: str) -> bytes | None:
    from rsmm.engine import corpus
    return corpus.read(f"{_HEROES_DIR}/{_hero_dir(hero)}/{file}{_GEN_SUFFIX}")


@cache
def _card_icon(hero: str, source: str) -> str | None:
    """The icon a talent card draws, as ``Heroes\\<Hero>\\<file>.png``.

    Found the way the skill kind finds the texture its ``icon`` overwrites (the
    first ``.png`` after the card's controller in the hero's entities), so the
    preview shows exactly what a replacement would replace. Guessing
    ``Skill <source>.png`` missed 33 of 278 cards: file names do not follow the
    controller names (Red's ``Secondary Quick Bombs`` draws ``Skill Special
    Quick Bombs``, Beowulf's ``Passive Ignite Explosion`` ``Skill_Crimson Fire``)."""
    from rsmm.sdk.content import ContentError
    from rsmm.sdk.kinds import skills as S
    try:
        decoded = S._slot_icon_texture(_herodefs()[hero], source)
    except (ContentError, KeyError):
        return None
    rel = decoded.removeprefix("Ui/").removesuffix(".Texture.dxt")
    return rel.replace("/", "\\")


def _hero_main(hero: str) -> bytes | None:
    from rsmm.engine import corpus
    folder = _hero_dir(hero)
    return corpus.read(f"{_HEROES_DIR}/{folder}/{folder}{_GEN_SUFFIX}")


@cache
def _hero_formats(hero: str) -> dict:
    """Text key -> ``(file, format)`` for every String Format of the hero that
    reads its ``Hero_<X>_Common~GAM.xls`` bank (the talent cards' bank)."""
    from rsmm.engine import corpus
    from rsmm.engine import item_modifier as IM
    main = _hero_main(hero) or b""
    m = re.search(rb"(Hero_[A-Za-z_]+_Common~GAM\.xls)", main)
    if m is None:
        return {}
    bank = m.group(1).decode()
    out: dict = {}
    for p in corpus.files(f"{_HEROES_DIR}/{_hero_dir(hero)}", _GEN_SUFFIX):
        file = p.name.split(".entity.ot.", 1)[0]
        for key, fmt in IM.formats_by_key(p.read_bytes(), bank).items():
            out.setdefault(key, (file, fmt))
    return out


@cache
def _hero_pngs(hero: str) -> tuple[str, ...]:
    """Every ``Heroes\\...png`` texture the hero's main entity names: its talent
    icons (``Skill Attack Dive.png``) and portrait. The icon route serves only
    these."""
    main = _hero_main(hero) or b""
    return tuple(sorted({m.group().decode() for m in
                         re.finditer(rb"Heroes\\[A-Za-z0-9_ \\]+\.png", main)}))


def hero_portrait(hero: str) -> str | None:
    return next((p for p in _hero_pngs(hero) if "\\Portrait_" in p), None)


@cache
def hero_png(hero: str, path: str) -> bytes | None:
    """A texture the hero's main entity names, decoded to PNG."""
    from rsmm.engine import corpus, icon_decode
    cards = {c["icon"] for c in talent_cards(hero) if c["icon"]}
    if path not in _hero_pngs(hero) and path not in cards:
        return None
    raw = corpus.read("Ui/" + path.replace("\\", "/") + ".Texture.dxt")
    if raw is None:
        return None
    try:
        return icon_decode.texture_to_png(raw, max_edge=256)
    except (ValueError, KeyError, IndexError):
        return None


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
    fields = {k: v for k, v in fields.items() if not k.startswith("_")}
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


#: A block's own files ride along in its fields under this key: relative path in
#: the mod -> bytes. Never written to the manifest; check() and save() put them
#: in the mod folder beside it (the PNG a custom icon is cooked from).
FILES = "_files"
_UPLOAD_MAX = 2 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _upload_png(data, what: str) -> bytes:
    """A PNG the page uploaded (base64, optionally a ``data:`` URL), checked."""
    if not isinstance(data, str) or not data:
        raise EditorError(f"{what}: no image")
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise EditorError(f"{what}: the image did not arrive intact") from None
    if len(raw) > _UPLOAD_MAX:
        raise EditorError(f"{what}: the image is over 2 MB")
    if not raw.startswith(_PNG_MAGIC):
        raise EditorError(f"{what}: the icon must be a PNG")
    return raw


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_") or "icon"


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
    upload = req.get("iconUpload")
    if upload:
        # Your own PNG: shipped in the mod, cooked by the item kind into a new
        # texture named after the item (Ui/Objects/UI_Object_<id>).
        rel = f"icons/{new_id}.png"
        fields["icon"] = rel
        fields[FILES] = {rel: _upload_png(upload, "icon")}
    elif isinstance(icon, str) and icon.strip():
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
    ``[{source, name?, description?}]`` and ``stats`` = ``[{file, modifier,
    stat}]``; only changed rows are sent."""
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
    from rsmm.engine.item_modifier import ItemModifierError, resolve_stat
    stats_by_file: dict[str, dict] = {}
    for row in req.get("stats") or []:
        file, modifier, stat = (str(row.get(k) or "") for k in ("file", "modifier", "stat"))
        if not file or not modifier or not stat:
            continue
        try:
            resolve_stat(stat)
        except ItemModifierError as e:
            raise EditorError(f"{modifier}: {e}") from None
        stats_by_file.setdefault(file, {})[modifier] = stat
    # Per-rarity numbers of a tier selector: union_patches by index.
    unions_by_file: dict[str, list] = {}
    for row in req.get("tiers") or []:
        file, label = str(row.get("file") or ""), str(row.get("label") or "")
        index = row.get("index")
        if not file or not label or not isinstance(index, int) or isinstance(index, bool):
            raise EditorError("a tier row needs its file, label and index")
        old, new = float(_num(row.get("old"), label)), float(_num(row.get("new"), label))
        if old != new:
            unions_by_file.setdefault(file, []).append(
                {"label": label, "index": index, "old": old, "new": new})
    out: list[tuple[str, str, dict]] = []
    for file in list(dict.fromkeys([*by_file, *stats_by_file, *unions_by_file])):
        slug = re.sub(r"[^A-Za-z0-9_]", "_", file.removeprefix(f"Hero_{hero}"))
        tid = f"{prefix}{slug}" if slug else prefix
        fields = {"kind": "talent", "id": tid, "hero": hero, "file": f"{file}.entity"}
        if by_file.get(file):
            fields["value_patches"] = by_file[file]
        if unions_by_file.get(file):
            fields["union_patches"] = unions_by_file[file]
        if stats_by_file.get(file):
            fields["stats"] = stats_by_file[file]
        out.append(("talent", tid, fields))
    for card in req.get("cards") or []:
        source = str(card.get("source") or "")
        if not source:
            raise EditorError("a card needs its source")
        fields: dict = {}
        for key in ("name", "description"):
            v = card.get(key)
            if isinstance(v, str) and v.strip():
                fields[key] = v
        sid = f"{prefix}_{re.sub(r'[^A-Za-z0-9_]', '_', source)}"
        if card.get("iconUpload"):
            # Cooked by the skill kind OVER this card's own icon texture.
            rel = f"icons/{_slug(hero)}_{_slug(source)}.png"
            fields["icon"] = rel
            fields[FILES] = {rel: _upload_png(card["iconUpload"], f"{source} icon")}
        if not fields:
            continue
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
            _write_files(assets.parent, fields)
            body = {k: v for k, v in fields.items()
                    if k not in ("kind", "id") and not k.startswith("_")}
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
    for _k, _i, fields in defs:
        _write_files(target, fields)
    manifest.write_text(new, encoding="utf-8")
    return manifest


def _write_files(mod_root: Path, fields: dict) -> None:
    """Write a block's own files (see FILES) under ``mod_root``. The paths are
    ones this module made (``icons/<slug>.png``), checked again here anyway."""
    for rel, data in (fields.get(FILES) or {}).items():
        if not re.fullmatch(r"icons/[A-Za-z0-9_]+\.png", rel):
            raise EditorError(f"refusing to write {rel!r} into a mod")
        dest = mod_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


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


# --- the compendium card's own assets ---------------------------------------

_RARITY_FRAME = {"Common": "01_Common", "Rare": "02_Rare", "Epic": "03_Epic",
                 "Legendary": "04_Legendary", "Cursed": "05_Cursed", "Powerups": "00_Power_Up"}

#: The textures the compendium's item card is drawn with, by the names the page
#: asks for. Read from GameUis/Items/Item_Description_Model (card, rarity plate,
#: super effect) and Item_Miniature_Model (the icon diamond). An allowlist, so the
#: route cannot be pointed at any other file.
CARD_TEXTURES: dict[str, str] = {
    "back": "Ui/Description/Description_Frame_Back.png",
    "super_bg": "Ui/Description/Description_SuperEffect_Bg.png",
    "super_border": "Ui/Description/Description_SuperEffect_border.png",
    "icon_bg": "Ui/Objects/Icon_Object_BackGround.png",
    "powerup_bg": "Ui/Objects/Icon_PowerUp_BackGround.png",
    **{f"frame_{r}": f"Ui/Description/Description_Frame_{r}.png"
       for r in ("Common", "Rare", "Epic", "Legendary", "Cursed")},
    **{f"plate_{r}": f"Ui/Description/Item_Rarity_Frame_{r}.png"
       for r in ("Common", "Rare", "Epic", "Legendary", "Cursed")},
    **{f"diamond_{r}": f"Ui/HUD/Object_Frame_{n}.png" for r, n in _RARITY_FRAME.items()},
    # A talent card's icon frame (GameUis/Items/Skill_Miniature).
    **{f"skill_{r}": f"Ui/HUD/HUD_Skill_Frame_{n}_Large.png"
       for r, n in (("Common", "01_Common"), ("Rare", "02_Rare"), ("Epic", "03_Epic"),
                    ("Legendary", "04_Legendary"), ("Ultimate", "05_Ultimate"))},
    "skill_slot": "Ui/HUD/HUD_Skill_Frame_Slot_Large.png",
}

#: The card's two fonts: the name is Germania One, every other line Fontin Sans.
CARD_FONTS: dict[str, str] = {
    "title": "Fonts/Germania One/Germania_One~GAM.fnt.Font.fnb",
    "body": "Fonts/Fontin Sans/Fontin_Sans_RG~GAM.fnt.Font.fnb",
}


@cache
def card_texture(name: str) -> bytes | None:
    """One card texture (or font page) decoded to PNG, from the install."""
    from rsmm.engine import corpus, icon_decode
    rel = CARD_TEXTURES.get(name)
    if rel is None and name.startswith("font_") and name[5:] in CARD_FONTS:
        font = card_font(name[5:])
        if font is None:
            return None
        rel = CARD_FONTS[name[5:]].rsplit("/", 1)[0] + "/" + font["page"]
    if rel is None:
        return None
    raw = corpus.read(rel + ".Texture.dxt")
    if raw is None:
        return None
    try:
        return icon_decode.texture_to_png(raw, max_edge=1024)
    except (ValueError, KeyError, IndexError):
        return None


@cache
def card_font(name: str) -> dict | None:
    """A card font's metrics and glyphs, as the page draws them."""
    from rsmm.engine import corpus, game_font
    rel = CARD_FONTS.get(name)
    raw = corpus.read(rel) if rel else None
    if raw is None:
        return None
    try:
        f = game_font.parse(raw)
    except ValueError:
        return None
    return {"page": f.page, "pageW": f.page_w, "pageH": f.page_h,
            "lineHeight": f.line_height, "size": f.size,
            "glyphs": {str(cp): list(g) for cp, g in f.glyphs.items()}}


def _card_texture(req: Request) -> Raw:
    png = card_texture(req.arg("name"))
    if png is None:
        raise Fail(404, "no such card texture")
    return Raw(png, "image/png", cache=True)


def _hero_png(req: Request) -> Raw:
    hero = req.arg("hero")
    if hero not in heroes():
        raise Fail(404, "no such hero")
    png = hero_png(hero, req.arg("path"))
    if png is None:
        raise Fail(404, "no such hero texture")
    return Raw(png, "image/png", cache=True)


def _card_font(req: Request) -> dict:
    font = card_font(req.arg("name"))
    if font is None:
        raise Fail(404, "no such card font")
    return font


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
    ("GET", "/api/cardtex"): _card_texture,
    ("GET", "/api/cardfont"): _card_font,
    ("GET", "/api/icon"): _icon,
    ("GET", "/api/heroes"): lambda req: {"heroes": heroes()},
    ("GET", "/api/talents"): lambda req: {"hero": req.arg("hero"),
                                          "files": talent_values(req.arg("hero")),
                                          "cards": talent_cards(req.arg("hero")),
                                          "portrait": hero_portrait(req.arg("hero"))},
    ("GET", "/api/heroes/portraits"): lambda req: {"portraits": {h: hero_portrait(h)
                                                                 for h in heroes()}},
    ("GET", "/api/heropng"): _hero_png,
    ("GET", "/api/mods"): lambda req: {"mods": list_mods(req.ctx.mods_dir)},
    ("POST", "/api/toml"): lambda req: {"toml": to_toml(_defs(req))},
    ("POST", "/api/check"): lambda req: {"toml": to_toml(d := _defs(req)), "results": check(d)},
    ("POST", "/api/save"): _save,
}
