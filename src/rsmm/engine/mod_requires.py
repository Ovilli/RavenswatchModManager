"""A mod's `[requires]` table: the oldest CLI / loader it can run on.

    [requires]
    cli    = 31   # data/cli_version.json `cli_version`
    loader = 58   # loader stamp: <game>/rsmm/loader.manifest.json, else the bundled one

A CLI older than the mod's content otherwise fails with an error about a field,
which reads as a mistake in the mod. This turns it into "update RSMM".
"""

from __future__ import annotations

from pathlib import Path

KEYS = ("cli", "loader")


def parse_requires(value) -> dict[str, int]:
    """Validate a manifest's `[requires]` table. Raises ValueError with a message
    fit to show an author; returns ``{}`` when absent."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"[requires] must be a table, got {type(value).__name__}")
    unknown = sorted(set(value) - set(KEYS))
    if unknown:
        raise ValueError("[requires] has unknown key(s): " + ", ".join(unknown)
                         + " (allowed: cli, loader)")
    out: dict[str, int] = {}
    for k, v in value.items():
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ValueError(f"[requires] {k} must be a positive integer, got {v!r}")
        out[k] = v
    return out


def running_cli_version() -> int:
    from rsmm.engine.cli_update import own_stamp
    return own_stamp()[0]


def effective_loader_version(game_dir: Path | None) -> int:
    """The loader that will run: the planted one if the game dir has one."""
    from rsmm.engine.loader_update import bundled_version, planted_manifest_version
    if game_dir is not None:
        planted = planted_manifest_version(game_dir)
        if planted is not None:
            return planted
    return bundled_version()


def unmet(requires: dict[str, int], game_dir: Path | None) -> str | None:
    """Why a mod with these requirements cannot be applied here, or None."""
    if not requires:
        return None
    need = requires.get("cli")
    if need is not None:
        have = running_cli_version()
        if need > have:
            return f"needs RSMM CLI v{need} or newer, this is v{have} - update RSMM"
    need = requires.get("loader")
    if need is not None:
        have = effective_loader_version(game_dir)
        if need > have:
            return (f"needs loader v{need} or newer, the installed loader is "
                    f"v{have} - run rsmm update-loader")
    return None
