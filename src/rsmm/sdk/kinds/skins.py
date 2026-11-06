"""``kind = "skin"`` — NEW skins for a shipped hero, in the hero's own skin list.

One block per hero::

    [[content]]
    kind = "skin"
    id   = "scarlet_skins"
    hero = "Scarlet"
    skins = [
      { name = "Crimson", description = "Red as the hood.", tint = "#c01818",
        icon = "art/crimson_icon.png" },
      { name = "Ghost", from = "Raven", albedo = "art/ghost_ALB.png" },
    ]

Each skin is a copy of an existing skin of that hero (``from``, default
``Default``) wearing a material of its own: the source skin's body material
with the mod's maps (``albedo`` / ``mra`` / ``normal``) or, with no art at all,
its albedo recoloured to ``tint``. It is appended to the hero's skin list, so
the hero keeps every shipped skin and the new ones show after them in the
book, always unlocked (no DLC, no quest).

What is written (all ADDED files except the herodef and its cache, which are
the shipped ones edited):

* ``Heroes\\<Hero>\\<Hero>_<Skin>.entity.ot`` + its preload cache — the skin
  entity (the source's, material swapped);
* ``<art>\\Textures\\M_<Hero>_<Skin>.mat.ot`` and its textures;
* the book icon (``icon``, or the source skin's);
* the title/description keys in the hero's skins text bank;
* the herodef with the skins appended (``engine.herodef_skins``) and its
  preload cache with the new icons.

The skins' GUIDs are derived from mod id + hero + skin id, so the profile
remembers a skin across re-applies and updates of the mod.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..content import ContentDef, ContentError, SchemaNotMined, written_this_run
from . import _common as C

_FIELDS = frozenset({"hero", "skins"})
_SKIN_FIELDS = frozenset({"id", "name", "description", "from", "icon", "tint",
                          "albedo", "mra", "normal"})
_TEXTURE_FIELDS = {"albedo": "ALB", "mra": "MRA", "normal": "NRM"}
#: Big enough to keep a hero's albedo crisp, small enough that the pure-Python
#: recolour of a tint stays a few seconds (memoised after the first apply).
_TINT_MAX_EDGE = 1024


def _err(block: str, msg: str) -> ContentError:
    return ContentError(f"skin {block}: {msg}")


def _skin_id(o: dict, n: int, block: str) -> str:
    raw = o.get("id") or o.get("name") or f"Skin{n}"
    sid = re.sub(r"[^A-Za-z0-9]", "", str(raw).title())
    if not sid or not sid[0].isalpha():
        raise _err(block, f"skins[{n}]: cannot make an id from {raw!r}; give it an `id` "
                          "of letters and digits")
    return sid[:40]


def skin_guid(mod_id: str, hero: str, skin_id: str) -> bytes:
    """Stable per (mod, hero, skin): the profile keys skins by this GUID."""
    return hashlib.sha256(f"rsmm-skin/{mod_id}/{hero}/{skin_id}".encode()).digest()[:16]


def _body_mat(entity_raw: bytes) -> str | None:
    """The body material a skin entity sets (same rule as hero_cook.resolve_base)."""
    from ...engine import entity_strings as ES
    ts = [t for _s, _o, t in ES.list_strings(entity_raw)]

    def after(key) -> str | None:
        return next((m for i, t in enumerate(ts) if key(t)
                     for m in ts[i + 1:i + 6] if m.endswith(".mat.ot")), None)
    return (after(lambda t: t.endswith("\\Base\\Character Mesh Material Value"))
            or after(lambda t: t.startswith("[Value]") and " Mesh " in t
                     and t.endswith(" Material Value")))


def _hero_mats(entity_raw: bytes, art_dir: str) -> list[str]:
    """Every material the skin entity sets from the hero's own art folder, in
    order, LowRes copies left out (they are swapped along with their source)."""
    from ...engine import entity_strings as ES
    out: list[str] = []
    for _s, _o, t in ES.list_strings(entity_raw):
        if (t.endswith(".mat.ot") and t.startswith(art_dir + "\\")
                and "_LowRes" not in t and t not in out):
            out.append(t)
    return out


def _hue_shifted(cooked_raw: bytes, rgb) -> bytes | None:
    """The texture recoloured toward ``rgb``: each pixel takes the tint's hue,
    keeps its own brightness, and its saturation moves halfway to the tint's,
    so shading, line art and highlights survive (a flat multiply reads as a
    dark silhouette). Alpha untouched. None when the format cannot be decoded."""
    import colorsys

    from ...engine import cooked, icon_decode
    from ...engine import prop_cook as PC
    from ...engine.cooked_schemas.texture import TextureHandler
    try:
        sch = TextureHandler.parse_payload(cooked.parse(cooked_raw).sections[-1].payload)
        px = icon_decode.decode_to_rgba(sch.pixels, sch.width, sch.height, sch.format_name)
    except (ValueError, KeyError, IndexError):
        return None
    px, w, h = icon_decode.resize_to_max(px, sch.width, sch.height, _TINT_MAX_EDGE)
    th, ts, _tv = colorsys.rgb_to_hsv(*rgb)
    cache: dict[bytes, bytes] = {}
    out = bytearray(len(px))
    for i in range(0, len(px), 4):
        key = bytes(px[i:i + 3])
        got = cache.get(key)
        if got is None:
            _h, s, v = colorsys.rgb_to_hsv(key[0] / 255, key[1] / 255, key[2] / 255)
            r, g, b = colorsys.hsv_to_rgb(th, (s + ts) / 2, v)
            got = cache[key] = bytes((int(r * 255), int(g * 255), int(b * 255)))
        out[i:i + 3] = got
        out[i + 3] = px[i + 3]
    return PC.cook_texture(icon_decode.rgba_to_png(bytes(out), w, h))


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    from ...engine import character_export as CE
    from ...engine import corpus
    from ...engine import entity_strings as ES
    from ...engine import hero_cook as H
    from ...engine import herodef_skins as HS
    from ...engine import herodefs as HD
    from ...engine import prop_cook as PC
    from ...engine import rsc_cache as RC
    from ...engine import text_patches as TP
    from .heros import _game_dir, _install_bank, _tint
    from .meshes import _mod_source

    block = defn.id
    C.validate_id("skin", block)
    f = defn.fields
    unknown = sorted(set(f) - _FIELDS)
    if unknown:
        raise _err(block, f"unsupported field(s) {unknown}; known: {sorted(_FIELDS)}")
    hero = f.get("hero")
    stem = HD.stem(hero) if isinstance(hero, str) else None
    if not stem:
        raise _err(block, f"`hero` must name a shipped hero ({', '.join(HD.names())})")
    entries = f.get("skins")
    if not isinstance(entries, list) or not entries or not all(isinstance(o, dict)
                                                              for o in entries):
        raise _err(block, "`skins` is a non-empty list of tables ({ name = ..., ... })")

    herodef_rel = H.herodef_rel(stem)
    herodef_dest = out_dir / Path(*herodef_rel.split("/"))
    if written_this_run(herodef_dest):
        raise _err(block, f"another block in this mod already adds skins to {hero}; "
                          "put all of a hero's skins in ONE block's `skins` list")
    herodef = corpus.read(herodef_rel)
    herodef_cache = corpus.read(RC.cache_path_for(herodef_rel))
    if herodef is None or herodef_cache is None:
        raise SchemaNotMined(f"skin {block}: {hero}'s herodef or its cache is not in "
                             "the corpus or the game install")
    game = _game_dir()
    app = H.pristine_app_settings(game)
    if app is None:
        raise SchemaNotMined("ApplicationSettings.ot is not in the game install")
    try:
        b = H.resolve_base(stem, app)
        shipped = HS.skins(herodef)
    except (H.HeroCookError, HS.HerodefSkinError) as e:
        raise _err(block, str(e)) from e

    # The bank the hero's own skins are titled in (Default uses Common~GAM).
    bank = next((s.title.bank for s in shipped
                 if s.title and s.title.bank.startswith("Hero_")), None)
    if bank is None:
        raise _err(block, f"{hero} has no skins text bank to add titles to")
    prefix = b.default_skin.rsplit("\\", 1)[-1].removesuffix("Default.entity.ot")
    ent_dir = b.default_skin.rsplit("\\", 1)[0]

    written: list[Path] = []

    def put(decoded: str, blob: bytes) -> None:
        dest = out_dir / Path(*decoded.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)

    by_name = {s.entity.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
               .removeprefix(prefix).lower(): s for s in shipped}
    seen: set[str] = set()
    specs: list[HS.NewSkin] = []
    pairs: dict[str, str] = {}
    keys: list[tuple[str, str]] = []
    icon_lines: list[str] = []
    for n, o in enumerate(entries):
        bad = sorted(set(o) - _SKIN_FIELDS)
        if bad:
            raise _err(block, f"skins[{n}]: unsupported field(s) {bad}; "
                              f"known: {sorted(_SKIN_FIELDS)}")
        sid = _skin_id(o, n, block)
        if sid.lower() in seen or sid.lower() in by_name:
            raise _err(block, f"skins[{n}]: {sid!r} is already a skin of {hero}")
        seen.add(sid.lower())
        name = o.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _err(block, f"skins[{n}]: needs a `name` (the title the book shows)")
        src_name = str(o.get("from") or "Default").replace(" ", "").lower()
        src = by_name.get(src_name)
        if src is None:
            raise _err(block, f"skins[{n}]: {hero} has no skin {o.get('from')!r}; have "
                              f"{', '.join(sorted(by_name))}")
        src_rel = H.entity_rel(src.entity)
        src_raw = corpus.read(src_rel)
        src_cache = corpus.read(RC.cache_path_for(src_rel))
        if src_raw is None or src_cache is None:
            raise SchemaNotMined(f"skin {block}: {src.entity} or its cache is missing")

        # The look: the source skin's materials cloned. `tint` recolours the
        # albedo of EVERY hero material the skin sets (Scarlet's wolf form has
        # its own); maps go on the body material.
        art: list[str] = []
        swaps: dict[str, str] = {}
        maps = {k: o[k] for k in _TEXTURE_FIELDS if o.get(k)}
        tag = f"{prefix}{sid}".removeprefix("Hero_")
        body = _body_mat(src_raw)
        targets: list[str] = []
        if maps:
            if body is None:
                raise _err(block, f"skins[{n}]: {src.entity}'s body material was not found")
            targets.append(body)
        rgb = _tint(o["tint"], block, f"skins[{n}]") if o.get("tint") is not None else None
        if rgb is not None:
            targets += [m for m in _hero_mats(src_raw, b.art_dir) if m not in targets]
        for k, donor in enumerate(targets):
            mat_raw = corpus.read(PC.art_cooked_path(donor))
            if mat_raw is None:
                raise _err(block, f"skins[{n}]: material {donor} was not found")
            slots = CE.material_slots(donor)
            mtag = tag if k == 0 else f"{tag}_{k}"
            repoint: dict[str, str] = {}
            if donor == body:
                for fld, slot in _TEXTURE_FIELDS.items():
                    if fld not in maps:
                        continue
                    if slot not in slots:
                        raise _err(block, f"skins[{n}]: {donor} has no {slot} map")
                    ref = f"{b.art_dir}\\Textures\\T_{mtag}_{slot}.tga"
                    put(PC.art_cooked_path(ref), PC.cook_texture(
                        _mod_source(out_dir, maps[fld], block, f"skins[{n}].{fld}").read_bytes()))
                    repoint[slots[slot]] = ref
                    art.append(f"3D|{ref}|oCTexture")
            alb = slots.get("ALB")
            if rgb is not None and alb and alb not in repoint:
                cooked_alb = corpus.read(PC.art_cooked_path(alb))
                tinted = _hue_shifted(cooked_alb, rgb) if cooked_alb else None
                if tinted is None:
                    raise _err(block, f"skins[{n}]: {alb} cannot be tinted")
                ref = f"{b.art_dir}\\Textures\\T_{mtag}_ALB.tga"
                put(PC.art_cooked_path(ref), tinted)
                repoint[alb] = ref
                art.append(f"3D|{ref}|oCTexture")
            if not repoint:
                continue
            mat_ref = f"{b.art_dir}\\Textures\\M_{mtag}.mat.ot"
            put(PC.art_cooked_path(mat_ref), PC.clone_material(mat_raw, repoint))
            art.append(f"3D|{mat_ref}|oCMaterial")
            swaps[donor] = mat_ref
            lowres = donor.replace(".mat.ot", "_LowRes.mat.ot")
            if lowres != donor:
                swaps.setdefault(lowres, mat_ref)

        new_ref = f"{ent_dir}\\{prefix}{sid}.entity.ot"
        new_rel = H.entity_rel(new_ref)
        put(new_rel, ES.replace_strings(src_raw, swaps, require_all=False) if swaps else src_raw)
        src_self = f"EntitySettings|{src.entity}|oCEntitySettingsResource"
        lines = (set(RC.parse(src_cache)) - {src_self}) | set(art) | {
            f"EntitySettings|{new_ref}|oCEntitySettingsResource"}
        put(RC.cache_path_for(new_rel), RC.render(sorted(lines)))

        # The book icon: the mod's, or the source skin's.
        icon = src.icon
        if o.get("icon"):
            icon = f"BookMenu\\Skins\\Icon_Skin_{prefix}{sid}.png"
            put(f"Ui/{icon.replace(chr(92), '/')}.Texture.dxt", PC.cook_texture(
                _mod_source(out_dir, o["icon"], block, f"skins[{n}].icon").read_bytes()))
            icon_lines.append(f"Ui|{icon}|oCTexture")

        key = f"RSMM_{re.sub(r'[^A-Za-z0-9]', '_', mod_id)}_{prefix}{sid}_Skin"
        pairs[f"{key}_Title"] = name.strip()
        pairs[f"{key}_Description"] = str(o.get("description") or name).strip()
        keys.append((f"{key}_Title", f"{key}_Description"))
        specs.append(HS.NewSkin(guid=skin_guid(mod_id, stem, sid), entity=new_ref, icon=icon,
                                title=HS.TextRef(bank, 0, ""), description=HS.TextRef(bank, 0, "")))

    # Text: the keys are appended to the hero's skins bank; each reference
    # carries the row its key lands on (the book reads by row).
    bank_gen = _install_bank(game, bank)
    rows = TP.appended_rows(bank_gen, list(pairs))
    dec = f"Text/{bank}.LocalText.gen"
    for tok, blob in TP.append_bank_keys(bank_gen, pairs).items():
        put(dec if tok == "__base__" else dec + tok, blob)
    specs = [HS.NewSkin(guid=s.guid, entity=s.entity, icon=s.icon,
                        title=HS.TextRef(bank, rows[t], t),
                        description=HS.TextRef(bank, rows[d], d))
             for s, (t, d) in zip(specs, keys, strict=True)]

    try:
        out = HS.add_skins(herodef, specs)
    except HS.HerodefSkinError as e:
        raise _err(block, str(e)) from e
    put(herodef_rel, out)
    if set(icon_lines) - set(RC.parse(herodef_cache)):
        # The book's icons preload with the hero; the skin entities do not
        # (HeroDef_LoadSkinEntity loads each through its own cache).
        put(RC.cache_path_for(herodef_rel),
            RC.render(sorted(set(RC.parse(herodef_cache)) | set(icon_lines))))
    return written
