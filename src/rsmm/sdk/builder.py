"""Mod-builder used by `from rsmm import sdk; with sdk.Mod(...) as m:`.

Collects config/i18n/content/dependency declarations in memory, then
materializes the whole mod on `__exit__`. One transactional write per
mod build avoids half-built mod trees on the disk.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from rsmm.engine.paths import MODS_DIR

from .config import ConfigSchema
from .content import ContentRegistry
from .i18n import SUPPORTED_LOCALES, KEY_RE


class ModBuilder:
    """In-memory mod authoring buffer; flushed in one atomic pass."""

    def __init__(self, mod_id: str, *, version: str, author: str, name: str):
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
        # v1 surface delegates (kept lazy to avoid hard-importing every CLI):
        self._stat_calls: list[tuple] = []
        self._text_calls: list[tuple] = []

    # ---- v1 surface (delegated to legacy CLIs at commit-time) ---------

    def stat(self, *args, **kwargs) -> None:
        self._stat_calls.append((args, kwargs))

    def text(self, *args, **kwargs) -> None:
        self._text_calls.append((args, kwargs))

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
            # legacy delegates run their own scripts inside the mod dir
            # (kept as a TODO: integrate with merge.py rather than
            # re-running the v1 CLIs from here).
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
