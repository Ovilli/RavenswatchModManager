"""rsmm CLI dispatch — install + lifecycle + SDK subcommands."""

from __future__ import annotations

import sys

# Guard for callers that invoke this dispatch module via an older
# interpreter (e.g. a stale `python` symlink picked up by a sidecar
# wrapper) — the surrounding package targets 3.11+ and the imports
# below would crash with a less actionable message.
if sys.version_info < (3, 11):  # noqa: UP036
    sys.exit(  # pragma: no cover
        f"rsmm requires Python 3.11 or newer (have {sys.version.split()[0]}). "
        "Upgrade Python and reinstall rsmm."
    )

import rsmm.engine.paths  # noqa: E402 — ensures package is importable

# Replaced by the entrypoint script (./rsmm) at import time so `--help`
# shows the rich top-level overview, not this dispatch module's docstring.
TOP_LEVEL_HELP: str | None = None


def _dispatch_module(modname: str, argv: list[str]) -> int:
    import importlib
    sys.argv = [modname.split(".")[-1], *argv]
    mod = importlib.import_module(modname)
    if hasattr(mod, "main"):
        return int(mod.main() or 0)
    print(f"module {modname} has no main()", file=sys.stderr)
    return 2


LEGACY = {
    "apply":         ("rsmm.cli.apply_mods",                 []),
    "list":          ("rsmm.cli.apply_mods",                 ["--list"]),
    # "restore" is handled explicitly above (avoids LEGACY dead-code).
    "doctor":        ("rsmm.cli.doctor",                     []),
    "watch":         ("rsmm.cli.watch",                      []),
    "build":         ("rsmm.cli.build",                      []),
    "run":           ("rsmm.cli.run",                        []),
    "merge":         ("rsmm.cli.merge",                      []),
    "compat":        ("rsmm.cli.compat",                     []),
    "lint":          ("rsmm.cli.lint",                       []),
    "test":          ("rsmm.cli.test",                       []),
}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(TOP_LEVEL_HELP or __doc__)
        return 0
    sub = argv[0]
    rest = argv[1:]

    if sub == "restore":
        # Strip --all from any position so ordering doesn't matter.
        rest = [a for a in rest if a != "--all"]
        return _dispatch_module("rsmm.cli.apply_mods", ["--restore-all", *rest])

    BUILTIN = {
        "new":               "rsmm.cli.cmd_new",
        "schema":            "rsmm.cli.cmd_schema",
        "install":           "rsmm.cli.cmd_install",
        "pack":              "rsmm.cli.cmd_pack",
        "log":               "rsmm.cli.cmd_log",
        "decode":            "rsmm.engine.ot_decoder",
        "rebuild-asset-map": "rsmm.engine.find_iyg",
        "install-loader":    "rsmm.cli.install_loader",
        "cook":              "rsmm.cli.cook",
        "uncook":            "rsmm.cli.uncook",
        "unify":             "rsmm.cli.unify",
    }
    if sub in BUILTIN:
        return _dispatch_module(BUILTIN[sub], rest)

    if sub == "gui":
        print(
            "rsmm gui has moved. Run the desktop app (`pnpm desktop:dev`) "
            "or open https://rsmm.dev in a browser. See docs/SETUP.md.",
            file=sys.stderr,
        )
        return 2

    SDK = {
        "json":       "rsmm.cli.json_bridge",
        "safe-mode":  "rsmm.cli.safe_mode",
        "sdk-doctor": "rsmm.cli.sdk_doctor",
        "docs-gen":   "rsmm.cli.docs_gen_cmd",
        "update":     "rsmm.cli.update_cmd",
        "collection": "rsmm.cli.cmd_collection",
    }
    if sub in SDK:
        return _dispatch_module(SDK[sub], rest)
    if sub in ("repo", "sign", "verify", "keygen"):
        return _dispatch_module("rsmm.cli.repo_cmd", [sub, *rest])

    if sub in LEGACY:
        mod, prefix = LEGACY[sub]
        return _dispatch_module(mod, [*prefix, *rest])

    print(f"unknown subcommand: {sub}", file=sys.stderr)
    print(TOP_LEVEL_HELP or __doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
