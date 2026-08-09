"""Static gates on the loader's hooking code. No game exe required, so these
run in CI — unlike scripts/verify_symbol_resolve.py, which needs the binary.

Two rules, both learned the hard way:

1. A detour target must be resolved by SEMANTIC name (``Sym::<Name>_Pattern``),
   never by a ``"FUN_<addr>"`` literal. Those literals are addresses from
   whatever build the code was written against. The pattern DB keeps them alive
   as legacy aliases, so they still resolve and still pass ``fn_verify`` — and
   then land in the middle of some function the routine was merged into. The
   analytics firehose, armed by default on every install, spent an unknown
   number of releases detouring 0x8d0 bytes inside an unrelated function.

2. Every MinHook install must go through ``rsmm::hook_install`` /
   ``hook_install_at``, which adds the .pdata entry-point check that
   ``fn_verify`` structurally cannot make. Nine files hand-rolled the sequence
   and only two of them checked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

LOADER_SRC = Path(__file__).resolve().parent.parent / "src" / "loader" / "src"

# Files still resolving by literal, with the reason. Shrink this list; never
# grow it. Each entry needs its routine relocated into data/symbols.json first
# (tools/relocate_stale_symbols.py), after which the literal becomes
# Sym::<Name>_Pattern and the file leaves this list.
LEGACY_LITERAL_ALLOWLIST = {
    # No symbol exists for these routines and no pattern is in the DB, so each
    # resolves to nothing and its capability disables itself. Relocate the
    # routine into data/symbols.json (tools/relocate_stale_symbols.py), then
    # switch the call to Sym::<Name>_Pattern and drop the entry from here.
    #
    # hook_skins.cpp used to hold five of these — all wrong on the shipped
    # build, one of them an aligned-array deallocator being called as a
    # vector-grow. All four of its symbols were relocated on 2026-08-09 and it
    # is now clean.
    "hook_skills.cpp": 1,
    "hook_spawn.cpp": 1,
}

_LITERAL = re.compile(r'"(FUN_1[0-9a-f]{8})"')
# MinHook calls that are legitimate outside the helper.
_EXEMPT_FILES = {
    # The helper's own implementation.
    "hook_util.cpp",
    # hook_lua must set its slot's `installed` flag BETWEEN MH_CreateHook and
    # MH_EnableHook — the other order let the game enter a detour while the
    # flag was still false, and the dispatcher's answer to that is "return 0
    # without calling the original", i.e. the hooked function silently did
    # nothing on its first call. That ordering is load-bearing and cannot be
    # expressed through hook_install, so the file keeps its own sequence and
    # calls hook_entry_warn for the .pdata check.
    "hook_lua.cpp",
}


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _sources() -> list[Path]:
    return sorted(LOADER_SRC.glob("*.cpp"))


def test_no_new_hardcoded_fun_literals():
    """Resolving by FUN_<addr> is resolving by an address from an old build."""
    found: dict[str, int] = {}
    for src in _sources():
        names = set(_LITERAL.findall(_strip_comments(src.read_text())))
        if names:
            found[src.name] = len(names)

    unexpected = {f: n for f, n in found.items() if f not in LEGACY_LITERAL_ALLOWLIST}
    assert not unexpected, (
        f"new FUN_<addr> literal(s) in {unexpected}. Add a symbol to "
        f"data/symbols.json and use Sym::<Name>_Pattern — a literal is an "
        f"address from the build you wrote it against, and it will resolve "
        f"mid-function after the routine is merged into a larger one."
    )
    regressions = {
        f: (n, LEGACY_LITERAL_ALLOWLIST[f])
        for f, n in found.items()
        if n > LEGACY_LITERAL_ALLOWLIST[f]
    }
    assert not regressions, f"literal count grew (file: got, allowed) {regressions}"

    # Shrinking is the goal, so keep the allowlist honest about what is left.
    cleared = {f for f in LEGACY_LITERAL_ALLOWLIST if f not in found}
    assert not cleared, (
        f"{cleared} no longer use FUN_<addr> literals — remove them from "
        f"LEGACY_LITERAL_ALLOWLIST so the gate keeps them clean"
    )


@pytest.mark.parametrize("src", _sources(), ids=lambda p: p.name)
def test_minhook_installs_go_through_the_guarded_helper(src: Path):
    """MH_CreateHook outside hook_util bypasses the .pdata entry-point check."""
    body = _strip_comments(src.read_text())
    if src.name == "hook_lua.cpp":
        # Exempt from the helper, NOT from the check — the entry-point test is
        # mandatory everywhere, only the install sequence differs.
        assert "hook_entry_warn" in body, (
            "hook_lua keeps its own MH_CreateHook/MH_EnableHook sequence, so it "
            "must call hook_entry_warn itself or mod-supplied addresses go "
            "unchecked"
        )
        pytest.skip("owns its install sequence; checked via hook_entry_warn")
    if src.name in _EXEMPT_FILES:
        pytest.skip("the helper's own implementation")
    assert "MH_CreateHook" not in body, (
        f"{src.name} calls MH_CreateHook directly. Use rsmm::hook_install "
        f"(pattern name) or hook_install_at (address you already hold) so the "
        f"target is checked against .pdata — fn_verify only proves the bytes "
        f"match, which a mid-function match also does."
    )


# Env vars that carry a VALUE rather than a yes/no. flag_enabled only answers
# "is this on", so these legitimately read the environment directly.
_VALUED_ENV_VARS = {"RSMM_RECONNECT_SECONDS", "RSMM_LOCALE", "RSMM_DATA",
                    "RSMM_GAME_DIR", "RSMM_MODS_DIR"}

_RAW_ENV = re.compile(r'GetEnvironmentVariableA\(\s*"(RSMM_[A-Z0-9_]+)"')


def test_boolean_flags_go_through_flag_enabled():
    """A yes/no opt-in read straight from the environment is invisible to the app.

    `flag_enabled` (loader.cpp) honours the environment variable AND the
    rsmm_loader_flags.json the desktop app writes. Several files instead had a
    private `env_truthy` over GetEnvironmentVariableA, so their features could
    only be armed from Steam launch options and the desktop flags panel
    silently did nothing — hero capture, the engine hook, the skin force-show
    and the IO modes were all unreachable from the UI that advertises them.
    """
    offenders: dict[str, list[str]] = {}
    for src in _sources():
        body = _strip_comments(src.read_text())
        found = [v for v in set(_RAW_ENV.findall(body)) if v not in _VALUED_ENV_VARS]
        if found:
            offenders[src.name] = sorted(found)
    assert not offenders, (
        f"boolean RSMM_* flag(s) read via GetEnvironmentVariableA instead of "
        f"flag_enabled(): {offenders}. flag_enabled also reads the desktop's "
        f"rsmm_loader_flags.json; a raw getenv makes the toggle in the app a "
        f"no-op. Add value-carrying vars to _VALUED_ENV_VARS instead."
    )
