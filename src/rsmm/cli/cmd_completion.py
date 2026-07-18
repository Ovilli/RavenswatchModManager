#!/usr/bin/env python3
"""rsmm completion — emit a shell tab-completion script.

Completes subcommand names (with one-line descriptions), per-command flags,
`symbols` sub-verbs, and — for the mod-taking commands — live mod ids read
from the mods directory.

    rsmm completion bash  > ~/.rsmm-completion.bash   # then source it (see below)
    rsmm completion zsh   > ~/.zsh/_rsmm              # fpath+=(~/.zsh); compinit
    rsmm completion fish  > ~/.config/fish/completions/rsmm.fish

Bash — the reliable install (works even without the bash-completion package,
and no need to open a new shell):

    rsmm completion bash > ~/.rsmm-completion.bash
    echo 'source ~/.rsmm-completion.bash' >> ~/.bashrc
    source ~/.rsmm-completion.bash

Tip: bash lists candidates on the *second* Tab. For a single-Tab list, add
`set show-all-if-ambiguous on` to ~/.inputrc.

The subcommand list is generated from the dispatch table (iter_commands), so
it can never drift from what `rsmm` actually routes. Mod ids are resolved at
completion time via the hidden `rsmm completion --list-mods`.
"""

from __future__ import annotations

import argparse
import sys

from rsmm.cli._dispatch import iter_commands

# Subcommands whose positional argument is a mod id. Completion offers live
# mod ids for these; everything else falls back to filename completion.
_MOD_COMMANDS = ("enable", "disable", "pack", "lint", "test")

# One-line descriptions shown next to each command. Keep terse.
_DESC: dict[str, str] = {
    "apply": "install mods into the game",
    "build": "asset map + loader + merge + apply",
    "collection": "manage mod collections",
    "compat": "analyze requires/conflicts/replaces graph",
    "completion": "emit a shell tab-completion script",
    "cook": "cook an asset into the game format",
    "decode": "dump an oCTextSaver cooked file",
    "disable": "disable mods",
    "docs-gen": "regenerate SDK/CLI reference docs",
    "doctor": "system health check",
    "enable": "enable mods",
    "enemies": "enemy-definition tools",
    "help": "show top-level help",
    "install": "install a packaged mod zip",
    "install-loader": "copy winhttp.dll + SDK lib into the game",
    "intents": "inspect/emit loader intent files",
    "items": "magic-item tools",
    "json": "JSON bridge for the desktop app",
    "keygen": "generate a signing keypair",
    "lint": "validate manifests + asset paths",
    "list": "show installed mods + their files",
    "log": "read the loader log",
    "menu": "in-game menu tools",
    "merge": "compose [[patch]] blocks into mods/_merged",
    "new": "scaffold a new mod",
    "pack": "bundle a mod into a zip",
    "rebuild-asset-map": "re-run find_iyg from UsedRscList.ot",
    "repo": "mod-repo signing/publishing",
    "restore": "roll back active overrides",
    "run": "launch Ravenswatch via Steam",
    "safe-mode": "toggle loader safe mode",
    "schema": "print/validate manifest schema",
    "sdk-doctor": "SDK environment health check",
    "sign": "sign a mod package",
    "symbols": "engine symbol-map tools",
    "talents": "hero-talent tools",
    "test": "diff build output vs fixture",
    "uncook": "decode a cooked asset to source",
    "unify": "unify/merge asset sources",
    "update": "self-update rsmm",
    "update-data": "refresh pattern DB / symbol data",
    "verify": "verify a signed mod package",
}

# `symbols` sub-verbs (mirrors cmd_symbols argparse).
_SYMBOLS_VERBS: dict[str, str] = {
    "list": "print the map grouped by category",
    "resolve": "show one symbol",
    "events": "gameplay events mods can subscribe to",
    "check": "validate the map",
    "gen": "generate loader header + python constants",
    "ghidra-export": "emit a Ghidra rename script",
}

# Best-effort per-command flag hints. `--help` remains the source of truth.
_FLAGS: dict[str, tuple[str, ...]] = {
    "apply": ("--dry-run", "--list"),
    "restore": ("--all",),
    "enable": ("--only", "--all"),
    "disable": ("--all",),
    "pack": ("--allow-vanilla",),
    "build": ("--skip-loader",),
    "run": ("--set-launch-options",),
    "watch": ("--interval",),
    "test": ("--record",),
    "log": ("-f", "--follow", "-n", "--lines", "--grep", "--all", "--prev",
            "--sessions", "--clear", "--path"),
    "install-loader": (),
}


def _commands() -> list[str]:
    seen: dict[str, None] = {}
    for name, _mod in iter_commands():
        seen.setdefault(name, None)
    seen.setdefault("completion", None)
    seen.setdefault("help", None)
    return sorted(seen)


def _list_mods() -> list[str]:
    # Lazy import so `--list-mods` stays fast and never triggers the game
    # directory scan for the completion-script emitters.
    from rsmm.engine.paths import MODS_DIR

    try:
        mods_dir = MODS_DIR
    except (OSError, RuntimeError, ValueError):
        return []
    if not mods_dir.is_dir():
        return []
    return [e.name for e in sorted(mods_dir.iterdir())
            if e.is_dir() and (e / "manifest.toml").exists()]


def _bash_assoc(name: str, mapping: dict[str, str]) -> str:
    """Render a bash associative-array literal from a name->desc mapping."""
    items = " ".join(
        f'[{k}]="{v}"' for k, v in mapping.items()
    )
    return f"local -A {name}=( {items} )"


def _bash_script(cmds: list[str]) -> str:
    cmd_list = " ".join(cmds)
    verb_list = " ".join(_SYMBOLS_VERBS)
    mod_cmds = "|".join(_MOD_COMMANDS)
    cmd_desc = _bash_assoc("_RSMM_DESC", {c: _DESC.get(c, "") for c in cmds})
    verb_desc = _bash_assoc("_RSMM_VERB_DESC", dict(_SYMBOLS_VERBS))
    flag_arms = "\n".join(
        f'        {name}) flags="{" ".join(flags)}" ;;'
        for name, flags in _FLAGS.items() if flags
    )
    return f"""# rsmm bash completion — generated by `rsmm completion bash`.
# Shows a "name  description" menu on Tab (bash 4+). Older bash falls back to
# plain names.
_rsmm_menu() {{
    # $1 = candidate names (space-separated), $2 = assoc-array var name.
    local -a matches
    matches=( $(compgen -W "$1" -- "$cur") )
    if [ "${{#matches[@]}}" -le 1 ] || [ "${{BASH_VERSINFO[0]}}" -lt 4 ]; then
        COMPREPLY=( "${{matches[@]}}" )
        return
    fi
    local -n _descmap="$2"
    COMPREPLY=()
    local m
    for m in "${{matches[@]}}"; do
        COMPREPLY+=( "$(printf '%-20s %s' "$m" "${{_descmap[$m]}}")" )
    done
    compopt -o nosort 2>/dev/null
}}

_rsmm_complete() {{
    local cur sub cword
    {cmd_desc}
    {verb_desc}
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    cword=$COMP_CWORD

    if [ "$cword" -eq 1 ]; then
        _rsmm_menu "{cmd_list}" _RSMM_DESC
        return 0
    fi

    sub="${{COMP_WORDS[1]}}"

    # `symbols <verb>` (verb is at word index 2).
    if [ "$sub" = symbols ] && [ "$cword" -eq 2 ]; then
        _rsmm_menu "{verb_list}" _RSMM_VERB_DESC
        return 0
    fi

    if [[ "$cur" == -* ]]; then
        local flags=""
        case "$sub" in
{flag_arms}
        esac
        COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
        return 0
    fi

    case "$sub" in
        {mod_cmds})
            local mods
            mods="$(rsmm completion --list-mods 2>/dev/null)"
            COMPREPLY=( $(compgen -W "$mods" -- "$cur") )
            ;;
        *)
            COMPREPLY=( $(compgen -f -- "$cur") )
            ;;
    esac
    return 0
}}
complete -F _rsmm_complete rsmm
"""


def _zsh_script(cmds: list[str]) -> str:
    def pairs(mapping: dict[str, str], keys) -> str:
        return " ".join(f"'{k}:{mapping.get(k, '')}'" for k in keys)

    cmd_pairs = pairs(_DESC, cmds)
    verb_pairs = pairs(_SYMBOLS_VERBS, _SYMBOLS_VERBS)
    mod_cmds = " ".join(_MOD_COMMANDS)
    flag_arms = "\n".join(
        f'      {name}) flags=({" ".join(flags)}) ;;'
        for name, flags in _FLAGS.items() if flags
    )
    return f"""#compdef rsmm
# rsmm zsh completion — generated by `rsmm completion zsh`. Descriptions native.
_rsmm() {{
  local -a cmds verbs
  cmds=({cmd_pairs})
  verbs=({verb_pairs})
  if (( CURRENT == 2 )); then
    _describe -t commands 'rsmm command' cmds
    return
  fi
  local sub=${{words[2]}}
  if [[ "$sub" == symbols && CURRENT == 3 ]]; then
    _describe -t verbs 'symbols verb' verbs
    return
  fi
  if [[ ${{words[CURRENT]}} == -* ]]; then
    local -a flags
    case "$sub" in
{flag_arms}
    esac
    compadd -- $flags
    return
  fi
  case "$sub" in
    {mod_cmds})
      local -a mods
      mods=(${{(f)"$(rsmm completion --list-mods 2>/dev/null)"}})
      compadd -- $mods
      ;;
    *)
      _files
      ;;
  esac
}}
_rsmm "$@"
"""


def _fish_script(cmds: list[str]) -> str:
    lines = ["# rsmm fish completion — generated by `rsmm completion fish`."]
    for c in cmds:
        desc = _DESC.get(c, "").replace("'", "")
        lines.append(
            f"complete -c rsmm -f -n '__fish_use_subcommand' -a {c} -d '{desc}'"
        )
    for v, desc in _SYMBOLS_VERBS.items():
        lines.append(
            "complete -c rsmm -f -n '__fish_seen_subcommand_from symbols' "
            f"-a {v} -d '{desc}'"
        )
    for c in _MOD_COMMANDS:
        lines.append(
            f"complete -c rsmm -n '__fish_seen_subcommand_from {c}' "
            "-a \"(rsmm completion --list-mods 2>/dev/null)\""
        )
    for name, flags in _FLAGS.items():
        for fl in flags:
            if fl.startswith("--"):
                lines.append(
                    f"complete -c rsmm -n '__fish_seen_subcommand_from {name}' "
                    f"-l {fl[2:]}"
                )
            elif fl.startswith("-") and len(fl) == 2:
                lines.append(
                    f"complete -c rsmm -n '__fish_seen_subcommand_from {name}' "
                    f"-s {fl[1:]}"
                )
    return "\n".join(lines) + "\n"


_EMITTERS = {"bash": _bash_script, "zsh": _zsh_script, "fish": _fish_script}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    ap = argparse.ArgumentParser(prog="rsmm completion", add_help=False)
    ap.add_argument("shell", nargs="?", choices=sorted(_EMITTERS),
                    help="shell to emit a completion script for")
    ap.add_argument("--list-mods", action="store_true",
                    help=argparse.SUPPRESS)  # hidden: used by the scripts
    ap.add_argument("-h", "--help", action="store_true")
    a = ap.parse_args(argv)

    if a.help or (not a.shell and not a.list_mods):
        print(__doc__)
        return 0
    if a.list_mods:
        for m in _list_mods():
            print(m)
        return 0

    print(_EMITTERS[a.shell](_commands()), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
