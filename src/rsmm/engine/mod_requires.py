"""A mod's `[requires]` table: the oldest CLI / loader it can run on.

    [requires]
    cli    = 31   # data/cli_version.json `cli_version`
    loader = 58   # judged from the installed winhttp.dll (see loader_install)

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


def loader_install(game_dir: Path) -> dict:
    """What loader the game dir actually holds, judged from the installed
    ``winhttp.dll`` and not from a stamp that can outlive it.

    ``{"state": "none" | "dev" | "release", "version": int | None}``:

    * no ``winhttp.dll`` -> ``none``;
    * DLL hash equals the ``loader.manifest.json`` winhttp.dll entry -> ``release``
      at the manifest's ``loader_version`` (a manifest with no such entry is
      trusted the same way);
    * otherwise DLL hash equals the DLL this CLI carries -> ``release`` at the
      bundled stamp (``install-loader`` plants that DLL and writes no manifest, and
      a stale manifest after a DLL swap does not matter);
    * anything else -> ``dev`` (``version`` is then only the manifest's, if any,
      and must not be relied on).
    """
    from rsmm.engine import loader_update as lu
    from rsmm.engine.hashing import sha256_file

    dll = game_dir / "winhttp.dll"
    if not dll.is_file():
        return {"state": "none", "version": None}
    manifest = lu.planted_manifest(game_dir)
    version = None
    if manifest is not None:
        v = manifest.get("loader_version")
        version = v if isinstance(v, int) and not isinstance(v, bool) else None
        entry = next((f for f in manifest.get("files") or []
                      if isinstance(f, dict) and f.get("path") == "winhttp.dll"), None)
        if not entry:
            return {"state": "release", "version": version}
        try:
            if sha256_file(dll) == entry.get("sha256"):
                return {"state": "release", "version": version}
        except OSError:
            return {"state": "release", "version": version}
    if lu.plant_matches_bundle(game_dir) is True:
        return {"state": "release", "version": lu.bundled_version()}
    return {"state": "dev", "version": version}


def effective_loader_version(game_dir: Path | None) -> int | None:
    """The version of the loader that will run, or None when it can't be
    confirmed (no loader, or a dev / unrecognized build)."""
    if game_dir is None:
        from rsmm.engine.loader_update import bundled_version
        return bundled_version()
    inst = loader_install(game_dir)
    return inst["version"] if inst["state"] == "release" else None


def check(requires: dict[str, int], game_dir: Path | None) -> dict:
    """Evaluate `[requires]` here: ``{"reason": str | None, "needs": {...},
    "warning": str | None}``. ``reason`` (set when the mod must be skipped) joins
    every unmet requirement; ``needs`` holds those requirements' numbers;
    ``warning`` is set when the loader requirement can't be confirmed."""
    reasons: list[str] = []
    needs: dict[str, int] = {}
    warning = None
    if not requires:
        return {"reason": None, "needs": needs, "warning": warning}
    need = requires.get("cli")
    if need is not None:
        have = running_cli_version()
        if need > have:
            reasons.append(f"needs RSMM CLI v{need} or newer, this is v{have} - update RSMM")
            needs["cli"] = need
    need = requires.get("loader")
    if need is not None:
        if game_dir is None:
            state, have = "release", effective_loader_version(None)
        else:
            inst = loader_install(game_dir)
            state, have = inst["state"], inst["version"]
        if state == "none":
            reasons.append(f"needs loader v{need}, no loader is installed - "
                           "run rsmm install-loader")
            needs["loader"] = need
        elif state == "dev" or have is None:
            warning = ("the installed loader is a dev or unrecognized build - "
                       f"can't confirm it has loader v{need}")
        elif need > have:
            reasons.append(f"needs loader v{need} or newer, the installed loader is "
                           f"v{have} - run rsmm update-loader")
            needs["loader"] = need
    return {"reason": "; ".join(reasons) or None, "needs": needs, "warning": warning}


def unmet(requires: dict[str, int], game_dir: Path | None) -> str | None:
    """Why a mod with these requirements cannot be applied here, or None."""
    return check(requires, game_dir)["reason"]
