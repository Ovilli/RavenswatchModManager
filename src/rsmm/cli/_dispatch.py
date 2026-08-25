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


#: Reserved internal verb — see `rsmm.cli.cmd_run_hook`. Kept here rather than
#: imported from that module so `main()` can route without importing it.
HOOK_RUNNER_VERB = "__on-disable"

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

BUILTIN = {
    "new":               "rsmm.cli.cmd_new",
    "items":             "rsmm.cli.cmd_items",
    "enemies":           "rsmm.cli.cmd_enemies",
    "talents":           "rsmm.cli.cmd_talents",
    "poi":               "rsmm.cli.cmd_poi",
    "schema":            "rsmm.cli.cmd_schema",
    "install":           "rsmm.cli.cmd_install",
    "pack":              "rsmm.cli.cmd_pack",
    "log":               "rsmm.cli.cmd_log",
    "overlay":           "rsmm.cli.cmd_overlay",
    "save":              "rsmm.cli.cmd_save",
    # The module already declares prog="rsmm cmd"; it was simply never routed.
    "cmd":               "rsmm.cli.console_cmd",
    # `menu` is the in-game mod menu; `home` is this CLI's own home screen.
    "menu":              "rsmm.cli.cmd_menu",
    "home":              "rsmm.cli.cmd_shell",
    "intents":           "rsmm.cli.cmd_intents",
    "decode":            "rsmm.engine.ot_decoder",
    "rebuild-asset-map": "rsmm.engine.find_iyg",
    "install-loader":    "rsmm.cli.install_loader",
    "cook":              "rsmm.cli.cook",
    "uncook":            "rsmm.cli.uncook",
    "unify":             "rsmm.cli.unify",
    "symbols":           "rsmm.cli.cmd_symbols",
    "update-data":       "rsmm.cli.cmd_update_data",
    "update-loader":     "rsmm.cli.cmd_update_loader",
    "changelog":         "rsmm.cli.cmd_changelog",
    "completion":        "rsmm.cli.cmd_completion",
}

SDK = {
    "json":       "rsmm.cli.json_bridge",
    "safe-mode":  "rsmm.cli.safe_mode",
    "sdk-doctor": "rsmm.cli.sdk_doctor",
    "docs-gen":   "rsmm.cli.docs_gen_cmd",
    "update":     "rsmm.cli.update_cmd",
    "collection": "rsmm.cli.cmd_collection",
}

# repo_cmd multiplexes these four under one module (passes the verb through).
REPO_ALIASES = ("repo", "sign", "verify", "keygen")

# cmd_mods multiplexes both toggle verbs under one module (verb passed through).
MOD_TOGGLE_ALIASES = ("enable", "disable")


def iter_commands():
    """Yield (command, target_module) for every dispatchable subcommand.

    Single source of truth for `rsmm docs-gen` so the generated CLI
    inventory can never silently drift from what `main()` actually routes.
    `restore` (folded into apply_mods) and `gui` (a redirect stub) are the
    only routes not modelled as a plain command->module pair.
    """
    yield "restore", "rsmm.cli.apply_mods"
    for name, (mod, _prefix) in LEGACY.items():
        yield name, mod
    for name, mod in BUILTIN.items():
        yield name, mod
    for name, mod in SDK.items():
        yield name, mod
    for name in REPO_ALIASES:
        yield name, "rsmm.cli.repo_cmd"
    for name in MOD_TOGGLE_ALIASES:
        yield name, "rsmm.cli.cmd_mods"


#: Group -> ordered (command, argument-summary, one-line description).
#:
#: The top-level help used to be a hand-maintained list in the `./rsmm`
#: docstring, which is exactly why it drifted: 23 of the 44 routed commands
#: had silently fallen out of it and were undiscoverable. `render_help()`
#: builds the listing from `iter_commands()` instead, and anything routed but
#: missing here still gets printed under "other", so a new subcommand can
#: never be invisible again. `tests/test_dispatch_help.py` enforces it.
COMMAND_GROUPS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("mods", (
        ("apply",    "[--dry-run]",                "install mods/ into the game"),
        ("restore",  "[--all]",                    "roll back active overrides"),
        ("list",     "[--files] [--enabled]",      "show installed mods"),
        ("enable",   "<id>... [--only|--all]",     "enable mods (--only: disable the rest)"),
        ("disable",  "<id>... [--all]",            "disable mods"),
        ("watch",    "[--interval N]",             "re-apply on every mods/ change"),
        ("merge",    "",                           "compose [[patch]] blocks into mods/_merged"),
    )),
    ("authoring", (
        ("new",      "<id>",                       "scaffold mods/<id>/"),
        ("lint",     "[<id>]",                     "validate manifests + asset paths"),
        ("test",     "[<id>] [--record]",          "diff build.py output vs checked-in fixture"),
        ("compat",   "",                           "analyze requires/conflicts/replaces graph"),
        ("pack",     "<id> [--allow-vanilla]",     "bundle mods/<id>/ into a zip"),
        ("build",    "[--skip-loader]",            "asset map + loader + merge + apply"),
        ("schema",   "",                           "emit the manifest JSON schema"),
        ("items",    "",                           "browse the magic-item corpus"),
        ("enemies",  "",                           "browse the enemy corpus"),
        ("talents",  "",                           "browse the talent corpus"),
        ("poi",      "[list|kinds|show]",          "browse map tiles / POIs"),
    )),
    ("game", (
        ("run",      "[--set-launch-options]",     "launch Ravenswatch via Steam"),
        ("install-loader", "[game-dir]",           "copy winhttp.dll + SDK lib into the install"),
        ("log",      "[-f] [-n N] [--grep S]",     "read the loader log"),
        ("overlay",  "[<mod>] [--watch]",          "live HUD data a mod publishes"),
        ("cmd",      "['/command'] [--tail]",      "send /commands to the in-game console"),
        ("menu",     "",                           "drive the in-game mod menu"),
        ("intents",  "",                           "apply queued in-game menu intents"),
        ("save",     "[path]... [--classes]",      "inspect profile saves (read-only)"),
    )),
    ("assets & engine", (
        ("cook",     "<file>",                     "encode an uncooked asset"),
        ("uncook",   "<file>",                     "decode a cooked asset"),
        ("unify",    "",                           "normalize an asset tree"),
        ("decode",   "<cooked-file>",              "dump oCTextSaver structure"),
        ("symbols",  "<gen|list|audit|events|…>",  "the engine symbol map"),
        ("rebuild-asset-map", "",                  "re-run find_iyg.py from UsedRscList.ot"),
        ("update-data", "",                        "fetch the rolling pattern DB"),
        ("update-loader", "",                      "fetch the loader DLL + Lua SDK"),
    )),
    ("distribution", (
        ("repo",     "",                           "manage a mod repository"),
        ("sign",     "<file>",                     "sign a mod bundle"),
        ("verify",   "<file>",                     "verify a signed bundle"),
        ("keygen",   "",                           "generate a signing keypair"),
        ("install",  "<id|url> [version]",         "fetch, verify and unpack a packed mod"),
        ("collection", "",                         "manage mod collections"),
        ("update",   "",                           "update installed mods"),
    )),
    ("system", (
        ("home",     "",                           "the interactive home screen (bare `rsmm`)"),
        ("changelog", "[--refresh] [-n N]",        "release notes from the rolling channel"),
        ("doctor",   "",                           "system health check (recommended often)"),
        ("sdk-doctor", "",                         "diagnose the SDK/loader surface"),
        ("safe-mode", "",                          "disable every mod and re-apply"),
        ("completion", "bash|zsh|fish",            "emit a shell tab-completion script"),
        ("docs-gen", "[--check]",                  "regenerate the SDK/CLI reference"),
        ("json",     "<payload>",                  "JSON bridge used by the desktop app"),
    )),
)

PREAMBLE = """rsmm — single CLI for Ravenswatch mod install + lifecycle.

Mods are written in Lua against the SDK. Drop a mod under `mods/<id>/`,
start its `init.lua` with `local R = require "rsmm"`, and use the
documented `R.*` API. See `docs/MODDING.md`."""


def render_help() -> str:
    """Build the top-level help from the routing table.

    Every command `main()` can dispatch appears here or under "other" — the
    listing is derived, not transcribed, so it cannot fall out of date.
    """
    from rsmm.cli import _term

    st = _term.Style()
    documented = {c for _g, rows in COMMAND_GROUPS for c, _a, _d in rows}
    routed = {name for name, _mod in iter_commands()}

    out = [PREAMBLE, ""]
    groups = list(COMMAND_GROUPS)
    leftover = sorted(routed - documented)
    if leftover:
        groups.append(("other", tuple((c, "", "") for c in leftover)))

    for title, rows in groups:
        shown = [r for r in rows if r[0] in routed]
        if not shown:
            continue
        out.append(st.heading(f"  {title}"))
        for cmd, args, desc in shown:
            usage = f"{cmd} {args}".rstrip()
            # Pad the PLAIN string: padding a styled one counts the ANSI
            # escapes as width and mis-aligns every row.
            padded = f"{usage:<36}"
            out.append(f"    {st.bold(padded)}{st.dim(desc)}")
        out.append("")

    out.append(st.dim("Help for any subcommand: `rsmm <cmd> --help`."))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        # Bare `rsmm` at an interactive terminal opens the home screen. Both
        # streams must be TTYs: piping or redirecting has to keep printing the
        # help text so scripts and the desktop sidecar are unaffected.
        if sys.stdin.isatty() and sys.stdout.isatty():
            return _dispatch_module("rsmm.cli.cmd_shell", [])
        print(TOP_LEVEL_HELP or render_help())
        return 0
    if argv[0] in {"-h", "--help", "help"}:
        print(TOP_LEVEL_HELP or render_help())
        return 0
    sub = argv[0]
    rest = argv[1:]

    if sub == "restore":
        # Strip --all from any position so ordering doesn't matter.
        rest = [a for a in rest if a != "--all"]
        return _dispatch_module("rsmm.cli.apply_mods", ["--restore-all", *rest])

    # Internal: how a FROZEN rsmm runs a mod's on_disable.py, since there is
    # no Python interpreter on disk to hand the script to. Deliberately not in
    # BUILTIN/SDK/LEGACY, so it stays out of `iter_commands()` and therefore
    # out of the help listing and the generated CLI docs.
    if sub == HOOK_RUNNER_VERB:
        return _dispatch_module("rsmm.cli.cmd_run_hook", rest)

    if sub in BUILTIN:
        return _dispatch_module(BUILTIN[sub], rest)

    if sub == "gui":
        print(
            "rsmm gui has moved. Run the desktop app (`pnpm desktop:dev`) "
            "or open https://rsmm.me in a browser. See docs/SETUP.md.",
            file=sys.stderr,
        )
        return 2

    if sub in SDK:
        return _dispatch_module(SDK[sub], rest)
    if sub in REPO_ALIASES:
        return _dispatch_module("rsmm.cli.repo_cmd", [sub, *rest])
    if sub in MOD_TOGGLE_ALIASES:
        return _dispatch_module("rsmm.cli.cmd_mods", [sub, *rest])

    if sub in LEGACY:
        mod, prefix = LEGACY[sub]
        return _dispatch_module(mod, [*prefix, *rest])

    print(f"unknown subcommand: {sub}", file=sys.stderr)
    print(render_help(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
