"""Whole-file overrides a declarative block could express instead.

A raw `assets/` override is the bottom of the override ladder (STRATEGY §8):
one owner, no merge, a copy of a game asset, and it silently reverts whatever
the next game patch changes in that file. Three families have a declarative
route that edits the game's own copy at apply time instead:

  * `[[patch]] kind = "stat"` for the fixed-layout stat files
    (`*.globalvalue.ot...`, game modifiers, enemy-camp difficulty);
  * `[[patch]] kind = "ot"` for a plaintext `.ot` shipped through `_root/`
    (ApplicationSettings.ot);
  * `[[content]] kind = "talent"` for a hero entity whose only changes are
    talent magnitudes.

`suggest_for_mod` finds raw overrides in those families and, when the vanilla
file is readable, writes the exact block. A block is only offered when it is
PROVEN: the snippet is parsed back with tomllib and fed through the same code
apply runs (`patch_field`, `ot_patch.apply_edits`, the talent kind's `emit`),
and the result must equal the mod's file byte for byte. Anything that does not
reproduce exactly — a structural edit, a GUID repoint, a shadowed value — is a
legitimate raw override and gets no nudge.

Read-only. Used by `rsmm lint` (prints the block) and `rsmm doctor` (one line
per mod).
"""

from __future__ import annotations

import json
import struct
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

#: Hero entity files, as the talent kind addresses them.
_HERO_PREFIX = "EntitySettings/Heroes/Hero_"
_ENTITY_SUFFIX = ".entity.ot.EntitySettingsResource.gen"


@dataclass
class Suggestion:
    decoded: str        # the mod's assets/ path
    route: str          # "stat" | "ot" | "talent"
    #: Manifest snippet that rebuilds the file from the game's own copy, or ""
    #: when the vanilla file was not readable and only the route is known.
    toml: str
    #: One line saying what to use instead.
    note: str

    @property
    def exact(self) -> bool:
        return bool(self.toml)


# --- value rendering ------------------------------------------------------------

def _f32(v: float) -> str:
    """Shortest decimal that packs to the same float32, as a TOML float."""
    bits = struct.pack("<f", v)
    s = repr(float(v))
    for p in range(1, 18):
        cand = f"{v:.{p}g}"
        if struct.pack("<f", float(cand)) == bits:
            s = repr(float(cand))
            break
    return s


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return json.dumps(str(v), ensure_ascii=False)


def _parse(snippet: str, table: str) -> dict | None:
    """The first `[[table]]` block of `snippet`, or None if it is not TOML.

    Every offer goes through this, so a snippet that would not load in a
    manifest (an unescapable string, a non-finite float) is never shown."""
    try:
        blocks = tomllib.loads(snippet).get(table) or []
    except tomllib.TOMLDecodeError:
        return None
    return blocks[0] if blocks else None


# --- stat -------------------------------------------------------------------------

def _stat_schema(decoded: str):
    from rsmm.engine.stat_schemas import SCHEMAS

    low = decoded.lower()
    return next((s for s in SCHEMAS if low.endswith(s.decoded_suffix.lower())), None)


def _short(decoded: str) -> str:
    return decoded.rsplit("/", 1)[-1].split(".", 1)[0]


def _stat_name_unique(decoded: str) -> bool:
    """`merge` finds a stat file by short name; a name two stat files share
    could land the patch on the other one."""
    from rsmm.engine.asset_map import decoded_to_encoded

    short = _short(decoded).lower()
    hits = [d for d in decoded_to_encoded()
            if _stat_schema(d) is not None
            and _short(d.replace("\\", "/")).lower() == short]
    return len(hits) == 1


def _body_fields(data: bytes, schema):
    from rsmm.engine.stat_schemas import MARK_BEGIN, MARK_END, _resolved

    lb, le = data.rfind(MARK_BEGIN), data.rfind(MARK_END)
    if lb == -1 or le <= lb:
        return None
    body = data[lb + 4:le]
    got = _resolved(schema, body)
    if got is None or len(body) != got[1]:
        return None
    return {fn: struct.unpack_from(fmt, body, off)[0] for fn, off, fmt in got[0]}, \
        {fn: fmt for fn, _off, fmt in got[0]}


def _suggest_stat(decoded: str, cur: bytes, van: bytes | None) -> Suggestion | None:
    from rsmm.engine.stat_schemas import patch_field

    schema = _stat_schema(decoded)
    if schema is None or not _stat_name_unique(decoded):
        return None
    name = _short(decoded)
    fields = ", ".join(fn for fn, _o, _f in schema.fields)
    note = (f'[[patch]] kind = "stat", name = "{name}" sets {fields} on the '
            f"game's own copy")
    if van is None:
        return Suggestion(decoded, "stat", "", note)
    a, b = _body_fields(van, schema), _body_fields(cur, schema)
    if a is None or b is None or len(cur) != len(van):
        return None
    (before, _), (after, fmts) = a, b
    changed = [fn for fn in after if after[fn] != before.get(fn)]
    if not changed:
        return None
    lines = ["[[patch]]", 'kind = "stat"', f"name = {_toml_value(name)}"]
    for fn in changed:
        v = after[fn]
        lit = (_f32(v) if fmts[fn] == "<f" else
               _toml_value(bool(v)) if fmts[fn] == "<?" else str(int(v)))
        lines.append(f"{fn} = {lit}")
    snippet = "\n".join(lines) + "\n"
    block = _parse(snippet, "patch")
    if block is None:
        return None
    out = van
    try:
        for fn in changed:
            out = patch_field(out, schema, fn, block[fn])
    except (ValueError, KeyError):
        return None
    return Suggestion(decoded, "stat", snippet, note) if out == cur else None


# --- ot ---------------------------------------------------------------------------

def _ot_value(prefix: str, raw: str):
    if prefix in ("i", "u"):
        return int(raw)
    if prefix == "b":
        if raw not in ("0", "1"):
            raise ValueError(raw)
        return raw == "1"
    if prefix == "f":
        return float(raw)
    return raw


def _suggest_ot(decoded: str, cur: bytes, van: bytes | None) -> Suggestion | None:
    from rsmm.cli.merge import DEFAULT_OT_FILE
    from rsmm.engine.ot_patch import (
        _FIELD_RE,
        DEFAULT_SELECTOR,
        OtPatchError,
        _block_of,
        apply_edits,
    )

    rel = decoded[len("_root/"):]
    note = ('[[patch]] kind = "ot" edits single fields of the game\'s own '
            f"{rel.rsplit('/', 1)[-1]}")
    if van is None:
        return Suggestion(decoded, "ot", "", note)
    try:
        new_t = cur.decode("utf-8")
        old_t = van.decode("utf-8")
    except UnicodeDecodeError:
        return None
    old, new = old_t.split("\n"), new_t.split("\n")
    if len(old) != len(new):
        return None
    owner = _block_of(old)
    labels: dict[int, list[str]] = {}
    for i, ln in enumerate(old):
        m = _FIELD_RE.match(ln.strip())
        if m and m.group("name") == DEFAULT_SELECTOR:
            labels.setdefault(owner[i], []).append(m.group("value"))
    edits: list[tuple[str, str, object]] = []
    for i, (a, b) in enumerate(zip(old, new, strict=True)):
        if a == b:
            continue
        ma, mb = _FIELD_RE.match(a.strip()), _FIELD_RE.match(b.strip())
        if not (ma and mb) or (ma.group("prefix"), ma.group("name")) != \
                (mb.group("prefix"), mb.group("name")):
            return None
        sel = labels.get(owner[i], [])
        if len(sel) != 1:
            return None          # no m_sLabel to select this block by
        try:
            value = _ot_value(mb.group("prefix"), mb.group("value"))
        except ValueError:
            return None
        edits.append((sel[0], mb.group("name"), value))
    if not edits:
        return None
    blocks = []
    for sel, field, value in edits:
        lines = ["[[patch]]", 'kind = "ot"']
        if rel != DEFAULT_OT_FILE:
            lines.append(f"file = {_toml_value(rel)}")
        lines += [f"selector = {_toml_value(sel)}", f"field = {_toml_value(field)}",
                  f"value = {_toml_value(value)}"]
        blocks.append("\n".join(lines) + "\n")
    snippet = "\n".join(blocks)
    try:
        parsed = tomllib.loads(snippet).get("patch") or []
        text, _ = apply_edits(old_t, [
            {"selector": p["selector"], "field": p["field"], "value": p["value"]}
            for p in parsed])
    except (tomllib.TOMLDecodeError, OtPatchError, KeyError):
        return None
    return Suggestion(decoded, "ot", snippet, note) if text == new_t else None


# --- talent -----------------------------------------------------------------------

def _hero_of(decoded: str) -> str | None:
    if not (decoded.startswith(_HERO_PREFIX) and decoded.endswith(_ENTITY_SUFFIX)):
        return None
    hero = decoded[len(_HERO_PREFIX):].split("/", 1)[0]
    return hero or None


def _suggest_talent(decoded: str, cur: bytes, van: bytes | None,
                    mod_id: str) -> Suggestion | None:
    """Only with the vanilla file: without it there is no telling whether the
    edit is a value change (expressible) or a structural one (not)."""
    from rsmm.engine import talent_values as TV
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import _common as KC
    from rsmm.sdk.kinds import talents

    hero = _hero_of(decoded)
    if hero is None or van is None or len(cur) != len(van):
        return None
    before = {v.label: v for v in TV.list_talent_values(van)}
    after = {v.label: v for v in TV.list_talent_values(cur)}
    if set(before) != set(after):
        return None
    rows = []
    for label, post in after.items():
        pre = before[label]
        if pre.value == post.value:
            continue
        exact = TV._read_value(cur, post.type_code, post.offset)
        new = (str(int(exact)) if post.type_code != TV.TYPE_F32 else _f32(exact))
        old = (str(int(pre.value)) if pre.type_code != TV.TYPE_F32
               else _f32(TV._read_value(van, pre.type_code, pre.offset)))
        clear = ", true" if pre.is_overridden and not post.is_overridden else ""
        rows.append(f"    [{_toml_value(label)}, {old}, {new}{clear}],")
    if not rows:
        return None
    stem = decoded.rsplit("/", 1)[-1][:-len(_ENTITY_SUFFIX)]
    cid = KC.slug_id(f"{mod_id}_{stem}").replace("-", "_")
    snippet = "\n".join([
        "[[content]]", 'kind = "talent"', f"id = {_toml_value(cid)}",
        f"hero = {_toml_value(hero)}", f"file = {_toml_value(stem + '.entity')}",
        "value_patches = [", *rows, "]"]) + "\n"
    block = _parse(snippet, "content")
    if block is None:
        return None
    fields = {k: v for k, v in block.items() if k not in ("kind", "id")}
    # Run the kind itself: a label that also lives in the hero's other entity
    # files would be patched there too, and only `emit` knows which those are.
    try:
        with tempfile.TemporaryDirectory(prefix="rsmm-suggest-") as tmp:
            written = talents.emit(mod_id, ContentDef("talent", block["id"], fields),
                                   Path(tmp))
            rels = [p.relative_to(tmp).as_posix() for p in written]
            same = rels == [decoded] and written[0].read_bytes() == cur
    except Exception:  # noqa: BLE001 — any failure means "not expressible"
        return None
    if not same:
        return None
    note = (f'[[content]] kind = "talent" patches {len(rows)} value(s) in '
            f"{hero}'s own file at apply time")
    return Suggestion(decoded, "talent", snippet, note)


# --- per mod ----------------------------------------------------------------------

def _vanilla_root_file(rel: str, game_dir: Path | None) -> bytes | None:
    """The game's pristine copy of a top-level install file (`_root/<rel>`)."""
    from rsmm.engine.paths import BACKUP_SUFFIX

    if game_dir is None:
        return None
    p = game_dir / Path(*rel.split("/"))
    for cand in (p.with_name(p.name + BACKUP_SUFFIX), p):
        try:
            return cand.read_bytes()
        except OSError:
            continue
    return None


def suggest_file(decoded: str, cur: bytes, *, mod_id: str = "mod",
                 game_dir: Path | None = None) -> Suggestion | None:
    """The declarative replacement for one raw override, if there is one."""
    from rsmm.engine import corpus

    if decoded.startswith("_root/"):
        if not decoded.endswith(".ot"):
            return None
        van = _vanilla_root_file(decoded[len("_root/"):], game_dir)
        return None if van == cur else _suggest_ot(decoded, cur, van)
    stat, hero = _stat_schema(decoded), _hero_of(decoded)
    if stat is None and hero is None:
        return None
    van = corpus.read(decoded)
    if van == cur:
        return None              # lint already says "identical to vanilla"
    if stat is not None:
        return _suggest_stat(decoded, cur, van)
    return _suggest_talent(decoded, cur, van, mod_id)


def suggest_for_mod(root: Path, *, game_dir: Path | None = None) -> list[Suggestion]:
    """Every raw override in `root/assets` a declarative block could replace.

    Files the mod's own `[[content]]` blocks emitted are not raw overrides and
    are skipped: those listed in `.rsmm_emitted.json`, and hero entities of a
    hero the mod already declares a `talent` block for (a committed emit
    output predates the marker in some mods)."""
    from rsmm.cli.apply_mods import is_skippable_asset

    assets = root / "assets"
    if not assets.is_dir():
        return []
    try:
        tbl = tomllib.loads((root / "manifest.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    meta = tbl.get("mod") if isinstance(tbl.get("mod"), dict) else {}
    mod_id = str(meta.get("id") or root.name)
    talent_heroes = {str(b.get("hero", "")).lower()
                     for b in tbl.get("content", []) or []
                     if isinstance(b, dict) and b.get("kind") == "talent"}
    try:
        emitted = set(json.loads((root / ".rsmm_emitted.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        emitted = set()

    out: list[Suggestion] = []
    for f in sorted(assets.rglob("*")):
        if not f.is_file():
            continue
        decoded = f.relative_to(assets).as_posix()
        if decoded in emitted or is_skippable_asset(decoded):
            continue
        hero = _hero_of(decoded)
        if hero is not None and hero.lower() in talent_heroes:
            continue
        try:
            s = suggest_file(decoded, f.read_bytes(), mod_id=mod_id, game_dir=game_dir)
        except OSError:
            continue
        if s is not None:
            out.append(s)
    return out
