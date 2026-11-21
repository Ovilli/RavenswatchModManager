from __future__ import annotations

import os

import pytest

from rsmm.cli import watch_restore as wr


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("RSMM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(wr.time, "sleep", lambda _s: None)


def _probe(monkeypatch, seq):
    """is_game_running() yields `seq`, then False forever."""
    it = iter(seq)
    monkeypatch.setattr(wr.game_proc, "is_game_running", lambda: next(it, False))


def _restore(monkeypatch, results):
    calls: list[int] = []
    it = iter(results)

    def fake():
        calls.append(1)
        return next(it), "boom"

    monkeypatch.setattr(wr, "_run_restore", fake)
    return calls


def _watch(**kw):
    args = {"interval": 0, "start_timeout": 60, "exit_probes": 3,
            "restore_attempts": 3, "retry_delay": 0, **kw}
    return wr.watch(**args)


def test_restores_after_game_starts_then_exits(monkeypatch):
    _probe(monkeypatch, [False, True, True])
    calls = _restore(monkeypatch, [True])
    assert _watch() == 0
    assert len(calls) == 1


def test_single_not_running_blip_does_not_restore(monkeypatch):
    # seen, then one false reading, then running again, then really gone
    probes = [True, False, True, True]
    state = {"n": 0}

    def probe():
        i = state["n"]
        state["n"] += 1
        return probes[i] if i < len(probes) else False

    monkeypatch.setattr(wr.game_proc, "is_game_running", probe)
    calls = _restore(monkeypatch, [True])
    assert _watch() == 0
    assert len(calls) == 1
    # the blip was not an exit: three further misses were needed after the last True
    assert state["n"] == len(probes) + 3


def test_never_seen_game_restores_anyway(monkeypatch):
    _probe(monkeypatch, [])
    calls = _restore(monkeypatch, [True])
    assert _watch(start_timeout=0) == 0
    assert len(calls) == 1
    assert "never saw the game" in (wr._log_path()).read_text(encoding="utf-8")


def test_restore_retries_then_gives_up(monkeypatch):
    _probe(monkeypatch, [True])
    calls = _restore(monkeypatch, [False, False, True])
    assert _watch() == 0
    assert len(calls) == 3

    _probe(monkeypatch, [True])
    calls = _restore(monkeypatch, [False, False, False])
    assert _watch() == 1
    assert len(calls) == 3
    assert "restore failed" in wr._log_path().read_text(encoding="utf-8")


def test_second_watcher_exits_immediately(monkeypatch):
    called = []
    monkeypatch.setattr(wr, "watch", lambda **_k: called.append(1) or 0)
    monkeypatch.setattr(wr.sys, "argv", ["watch-restore"])
    assert wr._acquire_lock()
    try:
        # a live pid other than ours owns the lock file
        lock = wr.user_data_dir() / wr.LOCK_NAME
        lock.write_text(str(os.getppid()), encoding="utf-8")
        monkeypatch.setattr(wr, "_pid_alive", lambda _p: True)
        assert wr.main() == 0
        assert called == []
        assert lock.read_text(encoding="utf-8") == str(os.getppid())
    finally:
        (wr.user_data_dir() / wr.LOCK_NAME).unlink(missing_ok=True)


def test_stale_lock_is_taken_over(monkeypatch):
    lock = wr.user_data_dir() / wr.LOCK_NAME
    lock.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(wr, "_pid_alive", lambda _p: False)
    assert wr._acquire_lock()
    assert lock.read_text(encoding="utf-8") == str(os.getpid())
    wr._release_lock()
    assert not lock.exists()


def _generations(monkeypatch, values):
    """read_launch_generation() yields `values`, then the last one forever."""
    it = iter(values)
    last = {"v": values[-1]}

    def read():
        v = next(it, last["v"])
        last["v"] = v
        return v

    monkeypatch.setattr(wr, "read_launch_generation", read)


def test_newer_modded_launch_is_watched_not_restored(monkeypatch):
    """Restart game: the old watcher must not restore under the relaunch.

    Session 1 runs and exits; a newer modded launch bumped the generation, so
    the watcher waits for session 2 and restores only after IT exits.
    """
    probes = [True, False, False, False,   # session 1 seen, then exits
              True, False, False, False]   # session 2 (the relaunch)
    _probe(monkeypatch, probes)
    _generations(monkeypatch, ["g1", "g2", "g2"])   # start, after s1, after s2
    calls = _restore(monkeypatch, [True])
    assert _watch() == 0
    assert len(calls) == 1
    log = wr._log_path().read_text(encoding="utf-8")
    assert "newer modded launch" in log
    assert log.count("game exited") == 2


def test_relaunch_during_restore_retries_stops_retrying(monkeypatch):
    # Restore fails once (files still locked), then a relaunch is recorded
    # before the second attempt: watch the new session instead.
    _probe(monkeypatch, [True, False, False, False, True])
    _generations(monkeypatch, ["g1", "g1", "g2", "g2"])
    calls = _restore(monkeypatch, [False, True])
    assert _watch() == 0
    assert len(calls) == 2           # one failed try, then one after session 2


def test_bump_changes_the_generation(tmp_path):
    before = wr.read_launch_generation()
    wr.bump_launch_generation()
    first = wr.read_launch_generation()
    wr.bump_launch_generation()
    assert first and first != before and wr.read_launch_generation() != first
