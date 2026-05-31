"""Mod-builder used by `from rsmm import sdk; with sdk.Mod(...) as m:`.

Collects config/i18n/content/dependency declarations in memory, then
materializes the whole mod on `__exit__`. One transactional write per
mod build avoids half-built mod trees on the disk.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from rsmm.engine.paths import MODS_DIR

from .api import sdk_export
from .config import ConfigSchema
from .content import ContentRef, ContentRegistry, _deref
from .i18n import KEY_RE, SUPPORTED_LOCALES

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


class ModBuilder:
    """In-memory mod authoring buffer; flushed in one atomic pass."""

    def __init__(self, mod_id: str, *, version: str, author: str, name: str):
        if not _ID_RE.match(mod_id):
            raise ValueError(f"invalid mod_id: {mod_id!r}")
        self.id = mod_id
        self.version = version
        self.author = author
        self.name = name
        self.enabled = True
        self._config_schema: dict | None = None
        self._i18n: dict[str, dict[str, str]] = {}
        self._content = ContentRegistry(mod_id=mod_id)
        self._requires: list[tuple[str, str]] = []
        self._api_name: str | None = None
        self._patch_blocks: list[dict] = []
        # decoded game-asset path -> source file to stage under assets/.
        self._assets: dict[str, Path] = {}
        # decoded path -> cook transform (orientation) sidecar payload.
        self._asset_transforms: dict[str, dict] = {}
        # custom skin-pack roster entries (loader detour reads these).
        self._skinpacks: list[dict] = []
        # tag id -> ordered, de-duped list of member resource ids.
        self._tags: dict[str, list[str]] = {}

    # ---- patch blocks (emitted as [[patch]] entries in manifest) ------

    def stat(self, name: str, **fields) -> None:
        self._patch_blocks.append({"kind": "stat", "name": name, **fields})

    def text(self, target: str, value: str, **fields) -> None:
        self._patch_blocks.append({"kind": "text", "target": target, "value": value, **fields})

    # ---- v3 surface ---------------------------------------------------

    def config(self, schema: dict) -> None:
        # Validate eagerly so the author sees errors before commit.
        ConfigSchema.from_dict(schema)
        self._config_schema = schema

    def i18n(self, locale: str, strings: dict) -> None:
        locale = locale.upper()
        if locale not in SUPPORTED_LOCALES:
            raise ValueError(f"unsupported locale: {locale}")
        for k in strings:
            if not KEY_RE.match(str(k)):
                raise ValueError(f"bad i18n key: {k!r}")
        self._i18n.setdefault(locale, {}).update({str(k): str(v) for k, v in strings.items()})

    def content(self, kind: str, *, id: str, **fields):
        """Low-level registration. Prefer the typed builders (:meth:`item`,
        :meth:`enemy`, …) which make required fields explicit and return a
        :class:`~rsmm.sdk.content.ContentRef` handle."""
        return self._content.register(kind, id=id, **fields)

    # ---- typed registry builders (Forge RegistryObject analog) --------
    #
    # Each returns a ContentRef you can pass into other defs (drop tables,
    # ability rosters, recipes); refs are deref'd to raw ids at register
    # time. `base` is the vanilla content to clone — required by every
    # schema-mined kind — so it is a positional-or-keyword on each builder.

    @sdk_export("Mod.item")
    def item(self, id: str, *, base: str, name: str | None = None, **fields):
        """Register a custom item cloned from vanilla ``base``."""
        if name is not None:
            fields["name"] = name
        return self._content.register("item", id=id, base=base, **fields)

    @sdk_export("Mod.enemy")
    def enemy(self, id: str, *, base: str, name: str | None = None, **fields):
        """Register a custom enemy cloned from vanilla ``base``."""
        if name is not None:
            fields["name"] = name
        return self._content.register("enemy", id=id, base=base, **fields)

    @sdk_export("Mod.boss")
    def boss(self, id: str, *, base: str, name: str | None = None, **fields):
        """Register a custom boss cloned from vanilla ``base``."""
        if name is not None:
            fields["name"] = name
        return self._content.register("boss", id=id, base=base, **fields)

    @sdk_export("Mod.map")
    def map(self, id: str, *, base: str, **fields):
        """Register a custom map/level cloned from vanilla ``base``."""
        return self._content.register("map", id=id, base=base, **fields)

    @sdk_export("Mod.hero")
    def hero(self, id: str, *, base: str, name: str | None = None,
             abilities: list | None = None, **fields):
        """Register a custom hero cloned from vanilla ``base``."""
        if name is not None:
            fields["name"] = name
        if abilities is not None:
            fields["abilities"] = abilities
        return self._content.register("hero", id=id, base=base, **fields)

    # ---- asset overrides (custom models / textures) -------------------

    # Source extensions the apply-time cooker knows how to turn into a
    # cooked asset (see engine.cook_cache.SOURCE_EXT_CLASS). Pre-cooked
    # binaries (.tpi/.dxt/...) are also allowed through untouched.
    _MODEL_EXTS = (".glb", ".gltf")
    _TEXTURE_EXTS = (".png", ".dds", ".tga")

    @sdk_export("Mod.asset")
    def asset(self, decoded_path: str, source: str | Path) -> None:
        """Stage a source asset to override the game file at `decoded_path`.

        `decoded_path` is the plaintext asset path as it appears in
        `data/asset_map.json` (forward slashes), e.g.
        ``3D/Characters/Heroes/Melusine/Textures/T_Melusine_ALB.png``.
        The file is copied verbatim into ``mods/<id>/assets/<decoded_path>``;
        `rsmm apply` auto-cooks source formats (.glb/.png/.dds/...) into the
        cooked container and installs them. Pre-cooked inputs pass through.
        """
        src = Path(source)
        if not src.is_file():
            raise FileNotFoundError(f"asset source not found: {src}")
        slashed = decoded_path.replace("\\", "/")
        if slashed.startswith("/") or (len(decoded_path) > 1 and decoded_path[1] == ":"):
            raise ValueError(f"decoded_path must be relative, got {decoded_path!r}")
        norm = slashed.strip("/")
        if not norm or ".." in norm.split("/"):
            raise ValueError(f"invalid decoded_path: {decoded_path!r}")
        if norm in self._assets:
            raise ValueError(f"duplicate asset override for {norm!r}")
        self._assets[norm] = src

    @sdk_export("Mod.model")
    def model(self, decoded_path: str, source: str | Path,
              rotate_deg: tuple[float, float, float] | None = None) -> None:
        """Override a mesh asset. Source must be a `.glb`/`.gltf`.

        A custom mesh is cooked at apply-time by retargeting it onto the
        game asset's skeleton (`engine.geometry_cook`). It is auto-scaled and
        recentered into the original's space; orientation defaults to an
        auto-upright guess (tallest axis -> up). If the mesh comes out turned
        or upside down, pass `rotate_deg=(x, y, z)` — a rigid rotation in
        degrees applied before the fit (e.g. `(90, 0, 0)` to flip upright,
        `(0, 180, 0)` to face the other way).
        """
        if Path(source).suffix.lower() not in self._MODEL_EXTS:
            raise ValueError(
                f"model() expects {self._MODEL_EXTS}, got {Path(source).suffix!r}")
        self.asset(decoded_path, source)
        if rotate_deg is not None:
            norm = decoded_path.replace("\\", "/").strip("/")
            self._asset_transforms[norm] = {
                "rotate_deg": [float(a) for a in rotate_deg]}

    @sdk_export("Mod.texture")
    def texture(self, decoded_path: str, source: str | Path) -> None:
        """Override a texture asset. Source must be a `.png`/`.dds`/`.tga`."""
        if Path(source).suffix.lower() not in self._TEXTURE_EXTS:
            raise ValueError(
                f"texture() expects {self._TEXTURE_EXTS}, got {Path(source).suffix!r}")
        self.asset(decoded_path, source)

    @sdk_export("Mod.skinpack")
    def skinpack(self, name: str, key: int, *, ac_id: str = "", al_id: str = "",
                 base_id: str = "") -> None:
        """Register a custom selectable skin-pack slot.

        The skin roster is hardcoded in the engine (a fixed 9 `oCAdditionalContent`
        "SkinPack" entries); see `docs/_re/kinds/skins.md`. A new slot can only be
        added at runtime, so this is realized by the native loader DLL
        (`src/loader/src/hook_skins.cpp`), which post-detours the roster builder and
        appends a standalone entry per def. Defs are staged to
        ``mods/<id>/skinpacks.json``; the loader aggregates them across enabled mods.

        Args:
            name:    display name shown in the skin grid.
            key:     pack key (int) the engine matches against a hero's pack-id
                     field (entry ``+0x3c``). Must be unique across packs.
            ac_id:   AC content id (entry ``+0x50``), e.g. ``RW000PSAC000000A``.
            al_id:   AL content id (entry ``+0x60``), e.g. ``RW000PSAL000000A``.
            base_id: base content id (entry ``+0x70``).

        Note: registering the slot is verified; whether a brand-new slot surfaces
        per-hero and resolves to a custom model/material is not yet confirmed
        in-game (see the "OPEN / UNVERIFIED" section of `docs/_re/kinds/skins.md`).
        Stage the per-skin cooked assets the resolver expects with
        :meth:`asset`/:meth:`texture`/:meth:`model` alongside this call.
        """
        if not name:
            raise ValueError("skinpack() needs a non-empty name")
        if not isinstance(key, int) or isinstance(key, bool):
            raise ValueError(f"skinpack() key must be an int, got {type(key).__name__}")
        if any(p["key"] == key for p in self._skinpacks):
            raise ValueError(f"duplicate skinpack key {key!r}")
        self._skinpacks.append({
            "name": name,
            "key": key,
            "ac_id": ac_id,
            "al_id": al_id,
            "base_id": base_id,
        })

    _TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_/]*$")

    @sdk_export("Mod.tag")
    def tag(self, tag_id: str, members) -> None:
        """Group content into a named, cross-mod-extensible tag (Minecraft
        ``#namespace:path`` tags analog).

        ``members`` is a ContentRef / id string, or an iterable of them.
        Calling ``tag()`` again with the same id **appends** (de-duped,
        order-preserved), so several mods — or several call sites — can grow
        one tag. Members are deref'd to raw ids, so you can pass the handles
        returned by :meth:`item`/:meth:`enemy`/… directly::

            dagger = m.item("RubyDagger", base="Knife")
            m.tag("daggers", [dagger, "VanillaKnife"])

        Tags are written to ``mods/<id>/tags.json``; downstream tooling/mods
        aggregate them (same model as ``skinpacks.json``).
        """
        if not self._TAG_RE.match(tag_id or ""):
            raise ValueError(
                f"tag id {tag_id!r} must match {self._TAG_RE.pattern} "
                "(lowercase, digits, '_' or '/')")
        if isinstance(members, (str, ContentRef)):
            members = [members]
        bucket = self._tags.setdefault(tag_id, [])
        for mem in members:
            rid = _deref(mem)
            if not isinstance(rid, str) or not rid:
                raise ValueError(f"tag {tag_id!r}: bad member {mem!r}")
            if rid not in bucket:
                bucket.append(rid)

    def requires(self, mod_id: str, version_spec: str = "") -> None:
        self._requires.append((mod_id, version_spec))

    def provides_api(self, name: str) -> None:
        self._api_name = name

    # ---- materialize --------------------------------------------------

    @sdk_export("Mod.summary")
    def summary(self) -> dict:
        """Snapshot of everything staged so far — print before :meth:`commit`
        to see exactly what the mod will write (no disk writes)."""
        by_kind: dict[str, list[str]] = {}
        for d in self._content.defs:
            by_kind.setdefault(d.kind, []).append(d.id)
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "content": by_kind,
            "assets": sorted(self._assets),
            "i18n_locales": sorted(self._i18n),
            "skinpacks": [p["name"] for p in self._skinpacks],
            "tags": {t: list(m) for t, m in self._tags.items()},
            "requires": [m for m, _ in self._requires],
            "provides_api": self._api_name,
        }

    @sdk_export("Mod.validate")
    def validate(self) -> list[str]:
        """Return human-readable warnings about the current state (does not
        raise). Empty list = clean. Called automatically by :meth:`commit`;
        run it yourself for a fast pre-flight."""
        warns: list[str] = []
        local_ids = {d.id for d in self._content.defs}
        for tag_id, members in self._tags.items():
            for rid in members:
                # A member that looks like a local id but isn't registered is
                # almost always a typo; external/vanilla ids are fine.
                if rid.isidentifier() and rid not in local_ids and ":" not in rid:
                    warns.append(
                        f"tag '{tag_id}': member '{rid}' is not a registered "
                        "content id in this mod (ok if it's a vanilla id)")
        if not any((self._content.defs, self._assets, self._skinpacks,
                    self._tags, self._patch_blocks, self._i18n)):
            warns.append("mod is empty — no content, assets, patches, or i18n")
        return warns

    def commit(self) -> Path:
        """Atomically write `mods/<id>/` from the accumulated state."""
        for w in self.validate():
            print(f"  [warn] {self.id}: {w}")
        dst = MODS_DIR / self.id
        with tempfile.TemporaryDirectory(prefix=f".rsmm_build_{self.id}_") as td:
            staging = Path(td) / self.id
            staging.mkdir(parents=True)
            self._write_manifest(staging)
            if self._config_schema is not None:
                self._write_config_schema(staging)
            if self._i18n:
                self._write_i18n(staging)
            if self._content.defs:
                (staging / "assets").mkdir(exist_ok=True)
                self._content.emit(staging / "assets")
            if self._assets:
                self._write_assets(staging)
            if self._skinpacks:
                self._write_skinpacks(staging)
            if self._tags:
                self._write_tags(staging)
            if dst.exists():
                shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging), str(dst))
        return dst

    # ---- helpers ------------------------------------------------------

    def _write_skinpacks(self, root: Path) -> None:
        (root / "skinpacks.json").write_text(
            json.dumps(self._skinpacks, indent=2) + "\n", encoding="utf-8")

    def _write_tags(self, root: Path) -> None:
        (root / "tags.json").write_text(
            json.dumps(self._tags, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_manifest(self, root: Path) -> None:
        lines = [
            "[mod]",
            f'id = "{self.id}"',
            f'name = "{self.name}"',
            f'version = "{self.version}"',
            f'author = "{self.author}"',
            f'enabled = {"true" if self.enabled else "false"}',
            'sdk_version = ">=3.0,<4"',
        ]
        if self._requires:
            lines += ["", "[dependencies]"]
            for mid, spec in self._requires:
                lines.append(f'{mid} = "{spec}"')
        if self._api_name:
            lines += ["", "[provides]", f'api = "{self._api_name}"']
        if self._patch_blocks:
            for block in self._patch_blocks:
                lines += ["", "[[patch]]"]
                for k, v in block.items():
                    if isinstance(v, bool):
                        lines.append(f'{k} = {"true" if v else "false"}')
                    elif isinstance(v, (int, float)):
                        lines.append(f'{k} = {v}')
                    else:
                        lines.append(f'{k} = "{v}"')
        (root / "manifest.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_config_schema(self, root: Path) -> None:
        s = self._config_schema or {}
        out = []
        for name, body in (s.get("fields") or {}).items():
            out.append(f"[fields.{name}]")
            for k, v in body.items():
                if isinstance(v, bool):
                    out.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, (int, float)):
                    out.append(f"{k} = {v}")
                elif isinstance(v, list):
                    rendered = ", ".join(f'"{str(x)}"' for x in v)
                    out.append(f"{k} = [{rendered}]")
                else:
                    out.append(f'{k} = "{v}"')
            out.append("")
        (root / "config_schema.toml").write_text("\n".join(out), encoding="utf-8")

    def _write_assets(self, root: Path) -> None:
        import json

        assets = root / "assets"
        assets.mkdir(exist_ok=True)
        for decoded, src in self._assets.items():
            dest = assets / decoded
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            tf = self._asset_transforms.get(decoded)
            if tf is not None:
                # Cook sidecar consumed by engine.cook_cache (orientation).
                dest.with_name(dest.name + ".rsmmcook").write_text(
                    json.dumps(tf), encoding="utf-8")

    def _write_i18n(self, root: Path) -> None:
        lang_dir = root / "lang"
        lang_dir.mkdir(exist_ok=True)
        for loc, table in self._i18n.items():
            lines = ["[strings]"]
            for k, v in sorted(table.items()):
                s = v.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{k} = "{s}"')
            (lang_dir / f"{loc}.toml").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
