"""Convention-over-configuration content discovery.

A mod's `manifest.toml` should say what the *mod* is — id, author, licence,
multiplayer scope — not carry a growing pile of `[[content]]` tables describing
every item, enemy and structure in it. This module moves the content out into
the file tree, the way Minecraft mods put a block in
`assets/<modid>/textures/block/foo.png` rather than in a registry file:

```
mods/my-mod/
    manifest.toml           what the mod is
    items/ember_charm/
        item.toml           what the item is
        icon.png
    enemies/frost_wolf/
        enemy.toml
    pois/runestone_shrine/
        poi.toml
        model.glb
        albedo.png
```

Each directory under a known kind folder is one content def. Its id defaults to
the folder name, and the `<kind>.toml` inside holds the fields the explicit
`[[content]]` block would have held. Discovery emits exactly that dict, so this
is a shorthand rather than a second code path — everything downstream
(validation, emit, lint, confidence gating) is unchanged.

A kind can take over its own discovery by exporting `discover(mod_root)` — see
:mod:`rsmm.sdk.kinds.poi`, which uses it to resolve donor presets and match art
files to texture slots by name. Kinds without one get the generic scan here.

Precedence: a `[[content]]` block in the manifest wins over a folder with the
same id, so an author can always drop to the explicit form for one def without
moving the rest.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .content import KINDS, ContentError

#: Folder name -> content kind. Plural directory, singular kind, matching how
#: the kinds already name themselves. Only kinds that make sense as "one def per
#: directory" are listed; `game_mode` is deliberately absent because a mod has
#: at most one and it belongs in the manifest.
KIND_DIRS: dict[str, str] = {
    "items": "item",
    "enemies": "enemy",
    "bosses": "boss",
    "heroes": "hero",
    "talents": "talent",
    "skills": "skill",
    "modifiers": "modifier",
    "rewards": "reward",
    "melodies": "melody",
    "maps": "map",
    "pois": "poi",
}

#: Accepted config filenames inside a def folder, most specific first. `<kind>`
#: is substituted per directory, so `items/foo/item.toml` and the generic
#: `items/foo/def.toml` both work.
CONFIG_NAMES = ("{kind}.toml", "def.toml")


def _load_config(folder: Path, kind: str) -> dict:
    for pattern in CONFIG_NAMES:
        p = folder / pattern.format(kind=kind)
        if p.is_file():
            try:
                return tomllib.load(p.open("rb"))
            except (OSError, tomllib.TOMLDecodeError) as e:
                raise ContentError(f"{kind} {folder.name}: {p.name} is not valid TOML: {e}") from e
    return {}


def _generic_scan(mod_root: Path, dirname: str, kind: str) -> list[dict]:
    """One def per subdirectory, fields straight out of its `<kind>.toml`."""
    root = mod_root / dirname
    if not root.is_dir():
        return []
    blocks: list[dict] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        cfg = _load_config(folder, kind)
        if not cfg:
            raise ContentError(
                f"{kind} {folder.name}: {folder} has no "
                f"{kind}.toml (or def.toml) — a content folder must say what it is."
            )
        block = {"kind": kind, "id": cfg.pop("id", None) or folder.name}
        block.update(cfg)
        blocks.append(block)
    return blocks


def discover(mod_root: Path) -> list[dict]:
    """Return `[[content]]`-shaped blocks for every def folder in `mod_root`.

    Ordering is by kind directory then folder name, so an apply is
    deterministic regardless of filesystem iteration order.
    """
    from importlib import import_module

    out: list[dict] = []
    for dirname, kind in sorted(KIND_DIRS.items()):
        if kind not in KINDS:
            continue
        if not (mod_root / dirname).is_dir():
            continue
        try:
            mod = import_module(f"rsmm.sdk.kinds.{_module_for(kind)}")
        except ModuleNotFoundError:
            mod = None
        custom = getattr(mod, "discover", None) if mod else None
        out.extend(custom(mod_root) if custom else _generic_scan(mod_root, dirname, kind))
    return out


def _module_for(kind: str) -> str:
    from .content import _KIND_MODULES

    return _KIND_MODULES.get(kind, f"{kind}s")


def merge_with_manifest(declared: list[dict], discovered: list[dict]) -> list[dict]:
    """Declared manifest blocks win over a discovered folder with the same id.

    Same-id collisions are matched per kind, so an `items/foo` folder and a
    `[[content]] kind="enemy" id="foo"` block do not shadow each other.
    """
    seen = {(b.get("kind"), b.get("id")) for b in declared}
    return list(declared) + [b for b in discovered
                             if (b.get("kind"), b.get("id")) not in seen]
