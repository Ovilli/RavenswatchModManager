"""Read/write the item-ban list a picker UI edits.

The desktop item picker must not hand-write TOML, and neither should a user
have to hand-edit a growing list of internal ids. This module owns one managed
mod whose only job is to carry a ban block, and exposes it as a plain set of
item ids: :func:`read_bans` / :func:`write_bans`.

The manifest is regenerated from the parsed document rather than patched
textually, so the ban list is the only thing that changes and any other key the
author added survives. Comments do not survive a rewrite, which is why this is
pointed at a MANAGED mod by default instead of at whatever mod happens to hold
a ban block.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Final

__all__ = ["DEFAULT_MOD_ID", "read_bans", "write_bans", "manifest_path",
           "migrate_legacy", "is_legacy_picker"]

#: The managed mod's id: reserved, so the store refuses to publish a mod under
#: it (packages/schemas `RESERVED_MOD_SLUGS`) and an install can never land in
#: the picker's folder. It used to be `banned-items`, an id the store also
#: publishes, so installing that mod replaced the player's picker mod.
DEFAULT_MOD_ID: Final = "rsmm-item-bans"
#: The id the managed mod had before; :func:`_migrate` moves a picker-written
#: one, and its "Sold out" placeholders keep their ids (items.placeholder_id).
LEGACY_MOD_ID: Final = "banned-items"
_BAN_BLOCK_ID: Final = "banned_items"
_ID_RE: Final = re.compile(r"^[A-Za-z0-9_.-]+$")

#: The picker, declared as a generic per-mod CONFIG field. Nothing here is
#: specific to the client: `multiselect` is a schema type any mod may use and
#: `source` names an allowlisted CLI option provider. The desktop renders it
#: with the same config panel it renders every other mod's settings with.
CONFIG_FIELD: Final = "banned"
_CONFIG_SCHEMA: Final[dict[str, Any]] = {
    "fields": {
        CONFIG_FIELD: {
            "type": "multiselect",
            "source": "item-catalog",
            "label": "Banned items",
            "default": [],
        },
    },
}

_DEFAULTS: Final[dict[str, Any]] = {
    "name": "Banned Items",
    "version": "1.0.0",
    "author": "RSMM",
    "description": (
        "Removes the selected magical objects from the game's catalog, so they "
        "can never be offered, dropped or found. Edited from the item picker."
    ),
    "enabled": True,
    "load_order": 50,
    "sdk_version": ">=3.0,<4",
    "license": "MIT",
    "tags": ["items", "challenge", "difficulty"],
    # The offer draw is seeded and host-authoritative deterministic, so a
    # per-peer runtime filter would desync. Banning in the data instead leaves
    # every peer with an identical pool -- provided every peer installs it.
    "multiplayer_scope": "deterministic-shared",
}


def mod_dir(mod_id: str = DEFAULT_MOD_ID, mods_dir: Path | None = None) -> Path:
    if mods_dir is None:
        from rsmm.engine import paths
        mods_dir = paths.MODS_DIR
    if mod_id == DEFAULT_MOD_ID:
        _migrate(Path(mods_dir))
    return Path(mods_dir) / mod_id


def _migrate(mods_dir: Path) -> None:
    migrate_legacy(mods_dir)


def _is_picker_mod(d: Path) -> bool:
    """Is ``d`` the picker's own mod (author ``RSMM`` and the picker schema)?"""
    if not (d / "manifest.toml").is_file():
        return False
    try:
        doc = _load(d / "manifest.toml")
    except ValueError:
        return False
    return (doc.get("mod") or {}).get("author") == _DEFAULTS["author"] and _has_picker_at(d)


def _unreadable_picker(d: Path) -> bool:
    """Picker data in ``d`` under a manifest that cannot be read: whose it is
    is unknown, so a caller that would delete the folder must stop."""
    if not (d / "manifest.toml").is_file() or not _has_picker_at(d):
        return False
    try:
        _load(d / "manifest.toml")
    except ValueError:
        return True
    return False


def is_legacy_picker(mods_dir: Path | None = None) -> bool:
    """Is the picker's mod still sitting at the legacy ``banned-items`` path?"""
    if mods_dir is None:
        from rsmm.engine import paths
        mods_dir = paths.MODS_DIR
    return _is_picker_mod(Path(mods_dir) / LEGACY_MOD_ID)


_ID_LINE_RE: Final = re.compile(
    r"""^(\s*(?:id|"id"|'id')\s*=\s*)(?:"(?:[^"\\]|\\.)*"|'[^']*')(\s*(?:#.*)?)$""")
_TABLE_RE: Final = re.compile(r"^\s*\[")
_MOD_HEADER_RE: Final = re.compile(r"""^\s*\[\s*(?:mod|"mod"|'mod')\s*\]\s*(#.*)?$""")


def _set_mod_id(manifest: Path, new_id: str) -> bool:
    """Set ``[mod].id`` whatever the quoting or spacing; True once it reads ``new_id``."""
    import tomllib
    try:
        text = manifest.read_text(encoding="utf-8")
        doc = tomllib.loads(text)
    except (OSError, ValueError):
        return False
    if (doc.get("mod") or {}).get("id") == new_id:
        return True
    out: list[str] = []
    in_mod = done = False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if _TABLE_RE.match(body):
            in_mod = _MOD_HEADER_RE.match(body) is not None
        elif in_mod and not done:
            m = _ID_LINE_RE.match(body)
            if m:
                line = f'{m.group(1)}"{new_id}"{m.group(2)}{line[len(body):]}'
                done = True
        out.append(line)
    new_text = "".join(out)
    try:
        if not done or (tomllib.loads(new_text).get("mod") or {}).get("id") != new_id:
            # An unusual layout (dotted keys, inline table): regenerate the
            # whole document so every other table survives.
            new_doc = dict(doc)
            new_doc["mod"] = {**(doc.get("mod") or {}), "id": new_id}
            new_text = _render_doc(new_doc)
        tmp = manifest.with_name(f"{manifest.name}.rsmm-new.{os.getpid()}")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(manifest)
    except (OSError, ValueError):
        return False
    return True


def migrate_legacy(mods_dir: Path | None = None) -> bool:
    """Move a picker-written ``banned-items`` to the reserved id.

    Only the picker's own mod is touched (written by :func:`write_bans`: author
    ``RSMM`` and the picker schema); a mod someone made under that name is left
    alone. Also repairs a reserved folder that still declares the old id (a
    crash between the move and the manifest rewrite), so a failed rewrite
    heals on the next call. Returns True when no picker is left at the legacy
    path, False when one is (migration failed and the folder was not touched).
    """
    if mods_dir is None:
        from rsmm.engine import paths
        mods_dir = paths.MODS_DIR
    mods_dir = Path(mods_dir)
    new, old = mods_dir / DEFAULT_MOD_ID, mods_dir / LEGACY_MOD_ID
    if not new.exists():
        if not _is_picker_mod(old):
            return not _unreadable_picker(old)
        try:
            os.replace(old, new)
        except OSError:
            return False
    if _is_picker_mod(new) and not _set_mod_id(new / "manifest.toml", DEFAULT_MOD_ID):
        return False
    return not (_is_picker_mod(old) or _unreadable_picker(old))


def manifest_path(mod_id: str = DEFAULT_MOD_ID, mods_dir: Path | None = None) -> Path:
    return mod_dir(mod_id, mods_dir) / "manifest.toml"


def _load(path: Path) -> dict[str, Any]:
    import tomllib
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: unreadable manifest ({e})") from e


def _is_ban_block(c: Any) -> bool:
    return (isinstance(c, dict) and c.get("kind") == "item"
            and c.get("mode") == "ban")


def _ban_blocks(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (doc.get("content") or []) if _is_ban_block(c)]


def read_bans(mod_id: str = DEFAULT_MOD_ID, mods_dir: Path | None = None) -> list[str]:
    """Item ids the managed mod currently bans (empty when it does not exist).

    The config picker's saved selection wins over the manifest list when it
    exists: the picker is the editing surface, so a manifest that disagrees is
    stale. A hand-authored mod with no config has no selection stored and keeps
    using its `items` list unchanged.
    """
    # When the mod HAS the picker, its value is the answer even when empty —
    # "nothing banned" is a real state. Falling through to the manifest on an
    # empty selection resurrected a stale list, so clearing the picker would
    # silently re-ban everything the list used to hold.
    if has_picker(mod_id, mods_dir):
        return read_config_selection(mod_id, mods_dir)

    doc = _load(manifest_path(mod_id, mods_dir))
    out: list[str] = []
    for block in _ban_blocks(doc):
        raw = block.get("items")
        if isinstance(raw, str):
            raw = [raw]
        out.extend(str(x) for x in (raw or []))
    return sorted(set(out))


def has_picker(mod_id: str = DEFAULT_MOD_ID, mods_dir: Path | None = None) -> bool:
    """Does this mod declare the `multiselect` ban picker?"""
    return _has_picker_at(mod_dir(mod_id, mods_dir))


def _has_picker_at(d: Path) -> bool:
    from rsmm.sdk.config import ConfigError, ConfigStore

    if not (d / "config_schema.toml").is_file():
        return False
    try:
        field = ConfigStore(d).schema.fields.get(CONFIG_FIELD)
    except (OSError, ConfigError, ValueError):
        return False
    return field is not None and field.type == "multiselect"


def read_config_selection(mod_id: str = DEFAULT_MOD_ID,
                          mods_dir: Path | None = None) -> list[str]:
    """The mod's `banned` config value, or [] when it has no config."""
    from rsmm.sdk.config import ConfigStore

    d = mod_dir(mod_id, mods_dir)
    if not (d / "config_schema.toml").is_file():
        return []
    try:
        value = ConfigStore(d).get(CONFIG_FIELD) or []
    except (OSError, ValueError):
        return []
    return sorted({str(x) for x in value}) if isinstance(value, list) else []


_BARE_KEY_RE: Final = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(k: str) -> str:
    return k if _BARE_KEY_RE.match(k) else _toml_value(k)


def _toml_value(v: Any, indent: str = "") -> str:
    import datetime
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dict):
        inner = ", ".join(f"{_toml_key(k)} = {_toml_value(x)}" for k, x in v.items())
        return "{ " + inner + " }"
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        inner = "".join(f"{indent}  {_toml_value(x)},\n" for x in v)
        return f"[\n{inner}{indent}]"
    s = str(v)
    body = s.replace("\\", "\\\\").replace('"', '\\"')
    body = body.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{body}"'


def _table(header: str, body: dict[str, Any], skip: tuple[str, ...] = ()) -> list[str]:
    out = [header]
    for k, v in body.items():
        if k in skip:
            continue
        out.append(f"{_toml_key(k)} = {_toml_value(v)}")
    return out


def _render(mod: dict[str, Any], blocks: list[dict[str, Any]]) -> str:
    lines = _table("[mod]", mod)
    for block in blocks:
        lines.append("")
        lines += _table("[[content]]", block)
    return "\n".join(lines) + "\n"


def _is_table_array(v: Any) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)


def _render_doc(doc: dict[str, Any]) -> str:
    """Every key of a parsed manifest: top-level scalars, then ``[mod]``, then
    each other table and array of tables."""
    lines = [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in doc.items()
             if not isinstance(v, dict) and not _is_table_array(v)]
    for k in sorted(doc, key=lambda k: k != "mod"):
        v = doc[k]
        if isinstance(v, dict):
            lines += ["", *_table(f"[{_toml_key(k)}]", v)]
        elif _is_table_array(v):
            for block in v:
                lines += ["", *_table(f"[[{_toml_key(k)}]]", block)]
    return "\n".join(lines).lstrip("\n") + "\n"


def _write_config(mod_id: str, items: list[str], mods_dir: Path | None) -> None:
    """Publish the picker's schema and store the selection through it.

    The schema is (re)written every time so an existing mod picks the picker up
    on the next write, and the value goes through :class:`ConfigStore` rather
    than a hand-rolled TOML dump — the store is what the desktop panel and the
    loader both read, and a second writer would be a second thing to keep in
    step.
    """
    from rsmm.sdk.config import ConfigStore

    d = mod_dir(mod_id, mods_dir)
    d.mkdir(parents=True, exist_ok=True)
    schema = d / "config_schema.toml"
    body = _table(f"[fields.{CONFIG_FIELD}]",
                  _CONFIG_SCHEMA["fields"][CONFIG_FIELD])
    schema.write_text("\n".join(body) + "\n", encoding="utf-8")

    store = ConfigStore(d)
    store.set(CONFIG_FIELD, items)


def write_bans(items: list[str], mod_id: str = DEFAULT_MOD_ID,
               mods_dir: Path | None = None) -> Path:
    """Set the managed mod's ban list to exactly ``items``.

    Creates the mod when absent. An empty list leaves the mod in place with an
    empty catalog edit rather than deleting it, so the next apply cleanly
    restores the full catalog and the user's other settings survive.
    """
    clean = sorted({str(i).strip() for i in items if str(i).strip()})
    bad = [i for i in clean if not _ID_RE.match(i)]
    if bad:
        raise ValueError(f"invalid item id(s): {', '.join(bad)}")

    path = manifest_path(mod_id, mods_dir)
    doc = _load(path)
    mod = dict(doc.get("mod") or {})
    for k, v in _DEFAULTS.items():
        mod.setdefault(k, v)
    mod["id"] = mod_id

    # Keep any non-ban content block the author added; replace every ban block
    # with the single one this function owns.
    blocks = [c for c in (doc.get("content") or [])
              if isinstance(c, dict) and not _is_ban_block(c)]
    # The block is a DECLARATION, not state, so it is written even for an empty
    # list. Dropping it when nothing is banned looked tidy and broke the mod:
    # the config picker writes only `config.toml`, so once the block was gone
    # nothing could put it back, `apply` had no content to emit, and every ban
    # made in the UI silently did nothing.
    blocks.append({"kind": "item", "mode": "ban",
                   "id": _BAN_BLOCK_ID, "items": clean})

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_config(mod_id, clean, mods_dir)
    # PID-qualified staging name: a shared one lets two processes' renames
    # eat each other (the same rule the loader plant follows).
    tmp = path.with_name(f"{path.name}.rsmm-new.{os.getpid()}")
    tmp.write_text(_render(mod, blocks), encoding="utf-8")
    tmp.replace(path)
    return path
