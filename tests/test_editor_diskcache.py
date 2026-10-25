"""Editor read answers kept on disk across launches (`cli/editor/diskcache`)."""

from __future__ import annotations

import json

import pytest

from rsmm.cli.editor import app, content, diskcache


@pytest.fixture
def counted(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(diskcache, "_fp", "fp-one")
    calls = []

    def heroes():
        calls.append(1)
        return ["Red", "Piper"]
    monkeypatch.setattr(content, "heroes", heroes)
    return calls


def _get(ctx, target="/content/api/heroes"):
    r = app.handle(ctx, "GET", target, {})
    return r.status, json.loads(r.data)


def test_a_second_launch_answers_from_disk(counted):
    assert _get(app.Context(disk_cache=True)) == (200, {"heroes": ["Red", "Piper"]})
    # A new process: nothing in memory, the answer comes off disk.
    assert _get(app.Context(disk_cache=True)) == (200, {"heroes": ["Red", "Piper"]})
    assert len(counted) == 1


def test_new_game_data_recomputes_and_drops_the_old_answers(counted, tmp_path, monkeypatch):
    _get(app.Context(disk_cache=True))
    monkeypatch.setattr(diskcache, "_fp", "fp-two")       # e.g. an apply ran
    _get(app.Context(disk_cache=True))
    assert len(counted) == 2
    assert [p.name for p in (tmp_path / "editor_cache").iterdir()] == ["fp-two"]


def test_off_by_default_and_for_unlisted_routes(counted, tmp_path):
    _get(app.Context())                                   # the web editor's bridge
    assert not (tmp_path / "editor_cache").exists()
    app.handle(app.Context(disk_cache=True), "GET", "/content/api/mods", {})
    assert not (tmp_path / "editor_cache").exists()


def test_cached_routes_exist():
    from rsmm.cli.editor import maps
    for mod in (content, maps):
        routes = {path for (method, path) in mod.ROUTES if method == "GET"}
        assert mod.CACHED <= routes, mod.CACHED - routes


# --- the slow-read gate: newest request first, departed clients skipped ------

def test_gate_serves_the_newest_waiter_first_and_skips_departed_ones():
    import threading
    import time

    gate = app._Gate()
    assert gate.enter(None)                     # a slow answer is running
    order, gone = [], threading.Event()

    def wait(name, alive=None):
        if gate.enter(alive):
            order.append(name)
            gate.leave()
        else:
            order.append(name + " left")

    threads = [threading.Thread(target=wait, args=("old",)),
               threading.Thread(target=wait, args=("aborted", lambda: not gone.is_set())),
               threading.Thread(target=wait, args=("new",))]
    for t in threads:
        t.start()
        time.sleep(0.05)
    gone.set()                                  # the aborted pick's browser hangs up
    time.sleep(0.3)
    gate.leave()
    for t in threads:
        t.join(2)
    assert order == ["aborted left", "new", "old"]


def test_game_data_answers_are_marked_for_the_web_editor(counted):
    r = app.handle(app.Context(), "GET", "/content/api/heroes", {})
    assert r.headers.get("X-RSMM-Cache") == "game"
    r = app.handle(app.Context(), "GET", "/content/api/mods", {})
    assert "X-RSMM-Cache" not in r.headers          # the player's own mods change
