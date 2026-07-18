"""Contract tests for the native-UI button bridge (hook_ui.cpp + the ``ui:press``
event mods subscribe to).

The C++ hook itself can't be exercised from Python, but two contracts can be
pinned so a refactor or game-patch churn can't silently break the feature:

1. ``rsmm lint`` must accept ``R.on("ui:press", ...)`` as a valid subscription
   (it's loader-emitted, not in the symbol map, so it must be allow-listed).
2. The hook's empirically-pinned widget offsets must stay *named constants* and
   the emitted event name must stay ``ui:press`` — the offsets are pinned from
   playtest, so an accidental magic-literal or rename is a real regression.
"""

from __future__ import annotations

from pathlib import Path

from rsmm.cli.lint import _lint_lua_api

_REPO = Path(__file__).resolve().parents[1]
_HOOK_UI = _REPO / "src" / "loader" / "src" / "hook_ui.cpp"


def _mod(tmp_path, lua: str) -> Path:
    (tmp_path / "init.lua").write_text(lua, encoding="utf-8")
    return tmp_path


def test_lint_accepts_ui_press_subscription(tmp_path):
    entry = _mod(tmp_path, 'R.on("ui:press", function(ev) end)\n')
    errs, warns = _lint_lua_api("m", entry)
    assert errs == 0
    assert warns == 0


def test_lint_still_warns_on_bogus_event(tmp_path):
    entry = _mod(tmp_path, 'R.on("uii:press", function(ev) end)\n')
    _errs, warns = _lint_lua_api("m", entry)
    assert warns >= 1        # a near-miss must not be silently swallowed


def test_hook_ui_source_keeps_named_offsets_and_event():
    src = _HOOK_UI.read_text(encoding="utf-8")
    # widget field offsets are named constexpr, not magic literals in-line
    assert "constexpr" in src and "kNameOff" in src and "kLabelOff" in src
    # the event contract the Lua side + lint allow-list depend on
    assert '"ui:press"' in src
    # a bounds guard must gate the widget dereference so a bad pointer can't fault
    assert "readable(" in src
