"""rsmm.sdk.engine — authoring-time view of the symbol map."""

from __future__ import annotations

import pytest

from rsmm.sdk import engine


def test_events_include_builtins_and_gameplay():
    evs = engine.events()
    assert {"setup", "ready", "tick", "exit"} <= set(evs)
    assert "level_up" in evs and "run_end" in evs
    assert evs == sorted(evs)


def test_callables_are_callable_symbols():
    names = engine.callables()
    assert "Resource_LookupByPath" in names
    for n in names:
        assert engine.is_callable(n)


def test_resolve_and_symbol():
    # Address tracks the current game build (updated by the remap pipeline),
    # so assert against the symbol map rather than a hardcoded literal.
    sym = engine.symbol("Resource_LookupByPath")
    assert sym.kind == "function"
    assert engine.resolve("Resource_LookupByPath") == int(sym.raw.split("_", 1)[1], 16)
    assert engine.symbol("nope") is None


def test_resolve_unknown_raises():
    with pytest.raises(KeyError):
        engine.resolve("Not_A_Symbol")


def test_predicates():
    assert engine.is_event("level_up") and not engine.is_event("levelup")
    assert engine.is_callable("Resource_LookupByPath")
    assert not engine.is_callable("g_MagicalObjectPool")  # data global, no cabi
