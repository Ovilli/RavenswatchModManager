"""Stopping the game, which is the other half of a loader update.

Planting the bundle does nothing for a session already running: the DLL is
loaded at process start, so the running game keeps the loader it started with.
Making the user find the window, close it, and go back to Steam is where "update
the loader" stops being one action.
"""
from __future__ import annotations

import rsmm.engine.game_proc as gp


def test_stop_is_a_noop_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr(gp, "is_game_running", lambda: False)
    called: list[list[str]] = []
    monkeypatch.setattr(gp, "_run", lambda cmd: called.append(cmd))
    assert gp.stop_game() is True
    assert called == [], "nothing to stop, so nothing should be signalled"


def test_stop_asks_politely_before_it_insists(monkeypatch):
    """SIGTERM / plain taskkill first: the engine gets a chance to flush its
    save. Only a process that ignores that gets killed."""
    signals: list[int] = []
    alive = {"n": 3}          # still up for the first few polls, then gone

    monkeypatch.setattr(gp.os, "name", "posix")
    monkeypatch.setattr(gp, "_pids", lambda: [4242] if alive["n"] > 0 else [])

    def running() -> bool:
        alive["n"] -= 1
        return alive["n"] > 0

    monkeypatch.setattr(gp, "is_game_running", running)
    monkeypatch.setattr(gp.os, "kill", lambda pid, sig: signals.append(sig))
    monkeypatch.setattr(gp.time, "sleep", lambda _s: None)

    assert gp.stop_game(grace_sec=5) is True
    assert signals == [gp.signal.SIGTERM], "a game that exits politely is never killed"


def test_stop_kills_a_process_that_ignores_the_polite_ask(monkeypatch):
    signals: list[int] = []
    monkeypatch.setattr(gp.os, "name", "posix")
    monkeypatch.setattr(gp, "is_game_running", lambda: True)   # never exits
    monkeypatch.setattr(gp, "_pids", lambda: [4242])
    monkeypatch.setattr(gp.os, "kill", lambda pid, sig: signals.append(sig))
    monkeypatch.setattr(gp.time, "sleep", lambda _s: None)

    assert gp.stop_game(grace_sec=0.01) is False   # honest: it is still there
    assert gp.signal.SIGTERM in signals
    assert gp.signal.SIGKILL in signals


def test_stop_survives_a_process_that_exits_underneath_it(monkeypatch):
    """The PID can go away between the scan and the signal; that is success,
    not an error to propagate into the UI."""
    monkeypatch.setattr(gp.os, "name", "posix")
    seen = {"n": 0}

    def running() -> bool:
        seen["n"] += 1
        return seen["n"] == 1

    monkeypatch.setattr(gp, "is_game_running", running)
    monkeypatch.setattr(gp, "_pids", lambda: [4242])

    def boom(pid: int, sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(gp.os, "kill", boom)
    monkeypatch.setattr(gp.time, "sleep", lambda _s: None)
    assert gp.stop_game(grace_sec=1) is True
