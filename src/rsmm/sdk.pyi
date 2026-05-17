"""
Public typing surface for `rsmm.sdk`.

Modders import `from rsmm import sdk` in their `mods/<id>/build.py`.
This stub gives IDEs (VS Code Pylance, PyCharm, etc.) hover docs and
autocomplete without forcing the runtime module to grow type imports.

Keep this in sync with src/rsmm/sdk.py — when a new SDK verb lands,
add its signature here too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Literal


class ValidationError(Exception):
    """Raised by Mod.validate() / Mod.__exit__ when a patch references
    an unknown asset / text key / option."""


class _Patch:
    kind: str
    args: dict[str, Any]
    owner: str
    def toml_block(self) -> str: ...


class Mod:
    """Build-time mod descriptor. Use as a context manager so the
    manifest is written exactly once.

        with sdk.Mod("MyMod", author="me", load_order=50) as m:
            m.stat("Bleed_Duration_Value", value=10)

    On __exit__ the SDK runs static validation against the asset map
    (catches typos before apply) and writes
    `mods/<id>/manifest.toml` with one [[patch]] block per call.
    """

    id: str
    name: str
    version: str
    author: str
    description: str
    enabled: bool
    load_order: int
    patches: list[_Patch]

    def __init__(
        self,
        id: str,
        *,
        name: str | None = None,
        version: str = "0.1.0",
        author: str = "",
        description: str = "",
        enabled: bool = True,
        load_order: int = 0,
    ) -> None: ...

    def __enter__(self) -> "Mod": ...
    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...

    # --- patch types ------------------------------------------------------

    def stat(
        self,
        name: str,
        value: float | None = None,
        *,
        min: float | None = ...,
        max: float | None = ...,
        **fields: float,
    ) -> "Mod":
        """Override a global numeric value or a difficulty band.

        Single-field globals (Bleed_Duration_Value, etc.) take `value`.
        Camp-difficulty bands take `min`/`max`. Discover names with
        `./rsmm stat --list`.
        """

    def text(self, bank: str, lang: str, key: str, value: str) -> "Mod":
        """Override a localization string. `lang` is one of EN JA KO RU
        ES DE PL FR IT PT-BR ZH-S ZH-T RO, or "ALL" to apply across
        every language."""

    def url(self, field_name: str, value: str) -> "Mod":
        """Override a main-menu URL field (DiscordUrl, etc.).
        Discover names with `./rsmm url --list`."""

    def texture(self, target: str, donor: str) -> "Mod":
        """Replace the cooked texture at `target` with the bytes of
        `donor`. Both arguments accept either decoded paths
        (`Ui/.../X.png.Texture.dxt`) or friendly aliases
        (`hero.romeo.portrait_active`). Discover aliases via
        `sdk.list_textures(grep=...)`."""

    def raw_file(
        self, decoded_path: str, src: Path | bytes | str
    ) -> "Mod":
        """Ship arbitrary cooked bytes at a decoded path. Use only
        when no higher-level patch type fits — raw drops have no
        field-merge, so two mods at the same path conflict."""

    # --- composite recipes ------------------------------------------------

    def rebalance_hero(
        self,
        hero: str,
        *,
        damage_mult: float | None = None,
        hp_mult: float | None = None,
        move_mult: float | None = None,
    ) -> "Mod":
        """High-level: scale a hero's damage / hp / move speed. Expands
        internally to the right [[patch]] blocks across multiple
        cooked files. Inspect the expansion with `./rsmm explain <id>`."""

    def replace_skin(
        self, hero: str, *, from_pack: str | Path
    ) -> "Mod":
        """Batch-swap every portrait/skin texture for a hero from a
        directory of donor PNGs. The directory's files must be named
        to match the target texture aliases."""

    # --- lifecycle --------------------------------------------------------

    def validate(self) -> None:
        """Run static validation now (also runs in __exit__). Raises
        ValidationError with all problems batched into one message."""

    def save(self) -> Path:
        """Write manifest.toml + any raw bytes to disk. Called
        implicitly by __exit__; expose for tests / dry-run flows."""

    def plan(self) -> list[dict]:
        """Return the patch plan as plain dicts (one per [[patch]]).
        Inspectable in tests without writing files."""


def list_textures(grep: str | None = None) -> list[str]:
    """Enumerate friendly texture aliases registered in the SDK.
    Pass `grep="Portrait"` to filter — useful for discovery in a REPL."""
