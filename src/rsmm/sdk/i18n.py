"""Localization bundle.

Each mod ships `lang/<locale>.toml`:

    [strings]
    title = "Frost Blade"
    desc  = "An icy weapon."

At apply time, RSMM merges strings into per-locale text-bank overrides
under namespaced keys: `RSMM_<modid>_<key>`. Locale codes match the
game's existing 12 (`apply_mods.LANG_DECODED_TO_ENCODED`) plus `RAW`.

At runtime, `R.i18n.t("key")` reads from a flat dict published by the
loader. This module is the host-side authoring + merging surface.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .api import sdk_export

SUPPORTED_LOCALES = (
    "EN", "JA", "KO", "RU", "ES", "DE", "PL", "FR", "IT",
    "PT-BR", "ZH-S", "ZH-T", "RAW",
)
FALLBACK_LOCALE = "EN"

KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass
class I18nBundle:
    """All locales' strings for a single mod."""

    mod_id: str
    by_locale: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, mod_id: str, mod_dir: Path) -> I18nBundle:
        bundle = cls(mod_id=mod_id)
        lang_dir = mod_dir / "lang"
        if not lang_dir.is_dir():
            return bundle
        for f in sorted(lang_dir.glob("*.toml")):
            locale = f.stem.upper()
            if locale not in SUPPORTED_LOCALES:
                raise ValueError(
                    f"{mod_id}: unknown locale '{f.stem}' in lang/; "
                    f"supported: {', '.join(SUPPORTED_LOCALES)}"
                )
            raw = tomllib.loads(f.read_text(encoding="utf-8"))
            strings = raw.get("strings") or {}
            cleaned: dict[str, str] = {}
            for k, v in strings.items():
                if not KEY_RE.match(k):
                    raise ValueError(
                        f"{mod_id}/{locale}: key {k!r} must match {KEY_RE.pattern}"
                    )
                cleaned[k] = str(v)
            bundle.by_locale[locale] = cleaned
        return bundle

    def namespaced(self, locale: str) -> dict[str, str]:
        """Return strings for `locale` with `RSMM_<modid>_` prefix applied.

        Missing locale falls back to `FALLBACK_LOCALE`. Returns `{}` if
        neither is present.
        """
        src = self.by_locale.get(locale) or self.by_locale.get(FALLBACK_LOCALE) or {}
        return {f"RSMM_{self.mod_id}_{k}": v for k, v in src.items()}

    def all_keys(self) -> set[str]:
        keys: set[str] = set()
        for _loc, table in self.by_locale.items():
            keys.update(table.keys())
        return keys

    def coverage_warnings(self) -> list[str]:
        """List of missing (locale, key) pairs vs the union of all keys.

        Useful for CI: a mod that supplies EN+DE strings but added a new
        key only in EN gets flagged.
        """
        all_keys = self.all_keys()
        msgs: list[str] = []
        for loc, table in sorted(self.by_locale.items()):
            missing = sorted(all_keys - table.keys())
            for k in missing:
                msgs.append(f"{self.mod_id}: locale {loc} missing key {k!r}")
        return msgs


@sdk_export("i18n.merge_bundles")
def merge_bundles(bundles: list[I18nBundle]) -> dict[str, dict[str, str]]:
    """Produce locale -> {namespaced_key: value} ready for text-bank merge.

    Two mods can't collide because keys are namespaced per `mod_id`.
    """
    out: dict[str, dict[str, str]] = {loc: {} for loc in SUPPORTED_LOCALES}
    for b in bundles:
        for loc in SUPPORTED_LOCALES:
            out[loc].update(b.namespaced(loc))
    return out
