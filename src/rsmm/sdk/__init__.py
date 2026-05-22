"""RSMM SDK v3 — Python-side public surface.

Mod authors do:

    from rsmm import sdk
    with sdk.Mod("MyMod") as m:
        m.stat(...)               # legacy v1 surface (delegated to cli.stat)
        m.text(...)               # legacy v1 surface (delegated to cli.text)
        m.config({"damage": {"type": "float", "default": 1.0}})
        m.i18n("EN", {"hello": "Hi"})
        m.content("item", id="FrostBlade", ...)

Everything below is a thin facade over the submodules so the mental
model is one import. See `docs/SDK_V3.md` for the full design.
"""

from __future__ import annotations

from .api import API_VERSION, require_api, sdk_export
from .config import ConfigSchema, ConfigStore
from .content import ContentDef, ContentRegistry
from .health import Health
from .i18n import I18nBundle
from .intermod import InterModRegistry
from .plugins import discover_plugins
from .repo import RepoIndex, sign_file, verify_file
from .transaction import ApplyTransaction
from .versioning import GameBuildPin, check_compat

__all__ = [
    "API_VERSION", "sdk_export", "require_api",
    "Health", "ConfigSchema", "ConfigStore", "I18nBundle",
    "ContentRegistry", "ContentDef", "InterModRegistry",
    "discover_plugins",
    "RepoIndex", "sign_file", "verify_file",
    "GameBuildPin", "check_compat",
    "ApplyTransaction",
    "Mod",
]


class Mod:
    """Mod-builder context for authors who write their mod in Python.

    Usage:

        with sdk.Mod("MyMod") as m:
            m.config({...})
            m.i18n("EN", {...})
            m.content("item", id="FrostBlade", base="VanillaSword",
                      stats={"damage": 50})

    `__exit__` materializes everything to `mods/<id>/` on disk in one
    transactional pass.
    """

    def __init__(self, mod_id: str, *, version: str = "0.0.1",
                 author: str = "", name: str | None = None):
        from .builder import ModBuilder
        self._b = ModBuilder(mod_id, version=version, author=author,
                             name=name or mod_id)
        # When set by `rsmm test`, __exit__ skips the on-disk commit so
        # the diff harness can introspect declarations without clobbering
        # the real mod tree.
        self.dry_run: bool = False

    def __enter__(self) -> Mod:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None and not self.dry_run:
            self._b.commit()

    def plan(self) -> list[dict]:
        """Return a stable JSON-serializable snapshot of declared build
        operations. Used by `rsmm test` to diff against checked-in fixtures.

        The list mixes entry kinds — `meta`, `config_schema`, `i18n`,
        `content`, `patch` — in a deterministic order so fixture diffs
        are reproducible.
        """
        out: list[dict] = [{
            "kind": "meta",
            "id": self._b.id,
            "name": self._b.name,
            "version": self._b.version,
            "author": self._b.author,
            "requires": sorted(self._b._requires),
            "api": self._b._api_name,
        }]
        if self._b._config_schema is not None:
            out.append({"kind": "config_schema", "schema": self._b._config_schema})
        for loc in sorted(self._b._i18n):
            out.append({"kind": "i18n", "locale": loc,
                        "strings": dict(sorted(self._b._i18n[loc].items()))})
        for d in self._b._content.defs:
            out.append({"kind": "content", "type": d.kind, "id": d.id,
                        "schema_version": d.schema_version,
                        "fields": d.fields})
        for block in self._b._patch_blocks:
            out.append({"kind": "patch", **block})
        return out

    # --- legacy v1 surface (delegated) ---------------------------------

    def stat(self, *args, **kwargs):
        return self._b.stat(*args, **kwargs)

    def text(self, *args, **kwargs):
        return self._b.text(*args, **kwargs)

    # --- v3 surface ----------------------------------------------------

    def config(self, schema: dict) -> None:
        self._b.config(schema)

    def i18n(self, locale: str, strings: dict) -> None:
        self._b.i18n(locale, strings)

    def content(self, kind: str, **fields) -> None:
        self._b.content(kind, **fields)

    def requires(self, mod_id: str, version_spec: str = "") -> None:
        self._b.requires(mod_id, version_spec)

    def provides_api(self, name: str) -> None:
        self._b.provides_api(name)
