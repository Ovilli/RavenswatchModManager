"""Mod-builder used by `from rsmm import sdk; with sdk.Mod(...) as m:`.

Collects config/i18n/content/dependency declarations in memory, then
materializes the whole mod on `__exit__`. One transactional write per
mod build avoids half-built mod trees on the disk.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from rsmm.engine.paths import MODS_DIR

from .config import ConfigSchema
from .content import ContentRegistry
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

    def content(self, kind: str, *, id: str, **fields) -> None:
        self._content.register(kind, id=id, **fields)

    # ---- asset overrides (custom models / textures) -------------------

    # Source extensions the apply-time cooker knows how to turn into a
    # cooked asset (see engine.cook_cache.SOURCE_EXT_CLASS). Pre-cooked
    # binaries (.tpi/.dxt/...) are also allowed through untouched.
    _MODEL_EXTS = (".glb", ".gltf")
    _TEXTURE_EXTS = (".png", ".dds", ".tga")

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

    def texture(self, decoded_path: str, source: str | Path) -> None:
        """Override a texture asset. Source must be a `.png`/`.dds`/`.tga`."""
        if Path(source).suffix.lower() not in self._TEXTURE_EXTS:
            raise ValueError(
                f"texture() expects {self._TEXTURE_EXTS}, got {Path(source).suffix!r}")
        self.asset(decoded_path, source)

    def requires(self, mod_id: str, version_spec: str = "") -> None:
        self._requires.append((mod_id, version_spec))

    def provides_api(self, name: str) -> None:
        self._api_name = name

    # ---- materialize --------------------------------------------------

    def commit(self) -> Path:
        """Atomically write `mods/<id>/` from the accumulated state."""
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
            if dst.exists():
                shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging), str(dst))
        return dst

    # ---- helpers ------------------------------------------------------

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
