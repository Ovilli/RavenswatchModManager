"""
High-level mod-authoring SDK. Modders write Python; the SDK hides the
asset-map lookup, cipher, and cooked-binary plumbing.

Usage:

    from rsmm import sdk

    with sdk.Mod("MyMod", author="me", version="1.0.0") as m:
        # Numeric balance patches. Other mods touching different fields
        # of the same cooked file will be merged automatically at apply
        # time.
        m.stat("Bleed_Duration_Value", value=10)
        m.stat("Easy", min=5, max=10)              # camp difficulty band

        # Text override; choose lang="ALL" to apply across every language.
        m.text("Common", lang="EN", key="Menu_Discord", value="Mods")

        # Main-menu URL.
        m.url("DiscordUrl", "https://example.com")

        # Texture donor swap.
        m.texture("hero.romeo.portrait_active",
                  donor="hero.sunwukong.portrait_active")

The Mod context writes `mods/<id>/manifest.toml` with `[[patch]]`
blocks and (optionally) `assets/` copies. `./rsmm apply` then composes
*all* mods' patches into a single coherent cooked output per file —
two mods editing different fields of the same balance constant both
take effect. Two mods editing the *same* field log a conflict and the
later mod (alphabetical id) wins.

For raw cooked-byte overrides (anything not yet supported as a patch
type), drop the file under `mods/<id>/assets/<decoded-path>` directly
or use `m.raw_file(decoded_path, src_bytes)`.
"""

from __future__ import annotations
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .engine.paths import MODS_DIR, DEFAULT_GAME_DIR, COOKING_SUBDIR
from .engine.asset_map import decoded_to_encoded


SDK_VERSION = "1.0"


class ValidationError(Exception):
    """Raised when an SDK call references an asset / field / key that
    doesn't exist or has an obviously wrong type. Surfaces at build
    time, not at apply time."""


# Multiplayer scope tags (see docs/STRATEGY.md §4).
MULTIPLAYER_SCOPES = {"cosmetic", "deterministic-shared",
                      "host-authoritative", "local-only"}


# Friendly aliases for common decoded paths. Modders use short names;
# the SDK expands them to the full decoded path before resolving via
# asset_map. Extend this table as the catalog grows.
TEXTURE_ALIASES: dict[str, str] = {}


def _populate_texture_aliases() -> None:
    """Best-effort auto-aliasing: <hero>.<state> -> the cooked tile.

    `hero.romeo.portrait_active` ->
        `Ui/BookMenu/Heroes/UI_HeroPortrait_Romeo_Active.png.Texture.dxt`
    """
    if TEXTURE_ALIASES:
        return
    am = decoded_to_encoded()
    for dec in am.keys():
        norm = dec.replace("\\", "/")
        if "/UI_HeroPortrait_" in norm and norm.endswith(".png.Texture.dxt"):
            base = norm.split("UI_HeroPortrait_", 1)[1].rsplit(".png.", 1)[0]
            parts = base.split("_")
            if len(parts) >= 2:
                hero = "_".join(parts[:-1]).lower()
                state = parts[-1].lower()
                TEXTURE_ALIASES[f"hero.{hero}.portrait_{state}"] = norm


def _resolve_texture(name: str) -> str:
    """Accepts either a decoded asset path or a friendly alias."""
    _populate_texture_aliases()
    if name in TEXTURE_ALIASES:
        return TEXTURE_ALIASES[name]
    return name.replace("\\", "/")


@dataclass
class _Patch:
    kind: str             # "stat" | "text" | "url" | "texture" | "raw"
    args: dict            # kind-specific payload

    def toml_block(self) -> str:
        lines = ["[[patch]]", f'kind = "{self.kind}"']
        for k, v in self.args.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f'{k} = "{v}"')
        return "\n".join(lines) + "\n"


@dataclass
class Mod:
    id: str
    name: str = ""
    version: str = "0.1.0"
    author: str = "you"
    description: str = ""
    enabled: bool = True
    load_order: int = 100   # lower applies first; ties broken alphabetically by id
    multiplayer_scope: str = "cosmetic"
    # Compatibility graph. Each entry is a mod id (optionally
    # "id >= 1.2"). See docs/STRATEGY.md §8.
    requires: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    sdk_version: str = SDK_VERSION
    patches: list[_Patch] = field(default_factory=list)
    raw_files: list[tuple[str, Path]] = field(default_factory=list)
    # Dry-run mode: SDK records calls, never writes files.
    dry_run: bool = False
    _root: Path | None = None

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.id
        if self.multiplayer_scope not in MULTIPLAYER_SCOPES:
            raise ValidationError(
                f"multiplayer_scope must be one of {sorted(MULTIPLAYER_SCOPES)}, "
                f"got {self.multiplayer_scope!r}"
            )
        self._root = MODS_DIR / self.id

    # --- context manager --------------------------------------------------
    def __enter__(self) -> "Mod":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            return
        # Static validation pass — surface typos at build time, not
        # at apply time.
        self.validate()
        if not self.dry_run:
            self.save()

    # --- patch types ------------------------------------------------------
    def stat(self, name: str, value: float | None = None, **fields) -> "Mod":
        """Patch a balance / modifier / camp-difficulty field.

        Single-field classes: stat("Bleed_Duration_Value", value=10).
        Multi-field classes:  stat("Easy", min=5, max=10).
        """
        args: dict = {"name": name}
        if value is not None:
            args["value"] = float(value)
        for k, v in fields.items():
            args[k] = float(v)
        self.patches.append(_Patch("stat", args))
        return self

    def text(self, bank: str, lang: str, key: str, value: str) -> "Mod":
        """Override a translation string in <bank> for <lang>.

        Use lang="ALL" to apply to every language.
        """
        self.patches.append(_Patch("text", {
            "bank": bank, "lang": lang, "key": key, "value": value,
        }))
        return self

    def url(self, field_name: str, value: str) -> "Mod":
        """Redirect a main-menu URL field (DiscordUrl, PatchNoteUrl, ...)."""
        self.patches.append(_Patch("url", {"field": field_name, "value": value}))
        return self

    def texture(self, target: str, donor: str) -> "Mod":
        """Swap target texture with donor's bytes.

        Both names accept either decoded asset paths
        (`Ui/.../UI_HeroPortrait_Romeo_Active.png.Texture.dxt`) or
        registered aliases (`hero.romeo.portrait_active`).
        """
        self.patches.append(_Patch("texture", {
            "target": _resolve_texture(target),
            "donor":  _resolve_texture(donor),
        }))
        return self

    def raw_file(self, decoded_path: str, src: Path | bytes | str) -> "Mod":
        """Drop a raw cooked file at <decoded_path>. Use only when no
        higher-level patch type fits. Loses field-level merge — one
        mod owns the whole file."""
        if self.dry_run:
            self.raw_files.append((decoded_path, Path("(dry-run)")))
            return self
        assert self._root is not None
        dest = self._root / "assets" / decoded_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(src, (bytes, bytearray)):
            dest.write_bytes(bytes(src))
        elif isinstance(src, (str, Path)):
            shutil.copyfile(src, dest)
        else:
            raise TypeError(f"src must be bytes/str/Path, got {type(src)}")
        self.raw_files.append((decoded_path, dest))
        return self

    # --- composite recipes (high-level helpers) --------------------------
    def rebalance_hero(self, hero: str, *,
                       damage_mult: float = 1.0,
                       hp_mult: float = 1.0,
                       speed_mult: float = 1.0) -> "Mod":
        """High-level: scale stats for a named hero.

        Expands to as many `[[patch]]` blocks as the engine RE allows.
        Today this is a *skeleton* — only the hero name is validated;
        actual per-stat fields land when oCEntitySettingsResource RE
        catches up. The SDK call shape is stable; backing impl is
        upgraded in place.
        """
        # Just record intent. Concrete float-patches require entity-body
        # schemas the framework doesn't yet have for hero defs.
        self.patches.append(_Patch("composite", {
            "kind": "rebalance_hero", "hero": hero,
            "damage_mult": float(damage_mult),
            "hp_mult":     float(hp_mult),
            "speed_mult":  float(speed_mult),
        }))
        return self

    def replace_skin(self, hero: str, *, from_pack: str | Path) -> "Mod":
        """High-level: swap all of a hero's portrait tiles from a
        donor mod or directory of texture files."""
        self.patches.append(_Patch("composite", {
            "kind": "replace_skin", "hero": hero,
            "from_pack": str(from_pack),
        }))
        return self

    # --- validation ------------------------------------------------------
    def validate(self) -> None:
        """Raise ValidationError if any patch references a name,
        asset, or field the engine doesn't expose. Called by
        __exit__ before save."""
        errors: list[str] = []
        am = decoded_to_encoded()

        # Texture target/donor existence
        for p in self.patches:
            if p.kind != "texture":
                continue
            for side in ("target", "donor"):
                path = p.args.get(side)
                if path not in am:
                    errors.append(f"texture {side}: not in asset_map: {path!r}")

        # Stat name existence: only if asset_map is available
        stat_names: set[str] = set()
        for dec in am:
            norm = dec.replace("\\", "/")
            if (".globalvalue.ot.GlobalEntityValueSettings.gen" in norm
                or ".gamemodifierdef.ot.meModifierDefinition.gen" in norm
                or ".enemycampdifficultydef.ot.DtEnemyCampDifficultyDefinition.gen" in norm):
                leaf = norm.rsplit("/", 1)[-1].split(".", 1)[0]
                stat_names.add(leaf.lower())
        for p in self.patches:
            if p.kind != "stat":
                continue
            name = str(p.args.get("name", "")).lower()
            if name and name not in stat_names:
                errors.append(f"stat: unknown field name {p.args['name']!r}")

        # Multiplayer-scope sanity
        if self.multiplayer_scope == "deterministic-shared":
            for p in self.patches:
                if p.kind == "composite":
                    errors.append(
                        "deterministic-shared mods cannot use composite "
                        "recipes yet (non-deterministic backing)"
                    )

        # Compatibility graph syntax
        for spec in (*self.requires, *self.conflicts, *self.replaces):
            if not spec or not isinstance(spec, str):
                errors.append(f"compat: empty or non-string entry: {spec!r}")

        if errors:
            joined = "\n  ".join(errors)
            raise ValidationError(
                f"{len(errors)} error(s) in mod {self.id!r}:\n  {joined}"
            )

    # --- emit -------------------------------------------------------------
    def save(self) -> Path:
        assert self._root is not None
        self._root.mkdir(parents=True, exist_ok=True)
        lines = ["[mod]"]
        lines.append(f'id                = "{self.id}"')
        lines.append(f'name              = "{self.name}"')
        lines.append(f'version           = "{self.version}"')
        lines.append(f'author            = "{self.author}"')
        if self.description:
            lines.append(f'description       = "{self.description}"')
        lines.append(f"enabled           = {str(self.enabled).lower()}")
        lines.append(f"load_order        = {self.load_order}")
        lines.append(f'multiplayer_scope = "{self.multiplayer_scope}"')
        lines.append(f'sdk_version       = "{self.sdk_version}"')
        if self.requires:
            lines.append("requires          = [" + ", ".join(f'"{s}"' for s in self.requires) + "]")
        if self.conflicts:
            lines.append("conflicts         = [" + ", ".join(f'"{s}"' for s in self.conflicts) + "]")
        if self.replaces:
            lines.append("replaces          = [" + ", ".join(f'"{s}"' for s in self.replaces) + "]")
        lines.append("")
        for p in self.patches:
            lines.append(p.toml_block())
        (self._root / "manifest.toml").write_text("\n".join(lines), encoding="utf-8")
        return self._root

    # --- introspection ---------------------------------------------------
    def plan(self) -> list[dict]:
        """Return a structured description of every patch this mod
        would produce. Useful for tests, doctor checks, and the
        `rsmm explain` command."""
        return [{"kind": p.kind, **p.args} for p in self.patches]


def list_textures(grep: str | None = None) -> list[str]:
    """Convenience for interactive use: every cooked texture path,
    optionally filtered by substring."""
    out = []
    for dec in decoded_to_encoded().keys():
        norm = dec.replace("\\", "/")
        if not norm.endswith((".png.Texture.dxt", ".tga.Texture.dxt",
                              ".tga.Texture.nrm")):
            continue
        if grep and grep.lower() not in norm.lower():
            continue
        out.append(norm)
    return sorted(out)
