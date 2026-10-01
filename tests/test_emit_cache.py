"""Apply-time caching: a mod whose inputs did not change is not re-emitted,
and an unchanged model or texture is not re-cooked (2026-10-01: a custom hero
cost ~40 s on every apply, whatever had changed)."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from rsmm.engine import cook_memo


def test_cook_memo_serves_a_repeat_from_cache_and_replays_its_warnings(caplog):
    calls = []

    def build():
        calls.append(1)
        logging.getLogger("rsmm.engine.geometry_cook").warning("mesh needed repair")
        return b"cooked"

    with caplog.at_level(logging.WARNING, logger="rsmm"):
        assert cook_memo.cached("model", (b"glb", b"donor"), build) == b"cooked"
        caplog.clear()
        assert cook_memo.cached("model", (b"glb", b"donor"), build) == b"cooked"
    assert len(calls) == 1, "an identical cook ran twice"
    assert [r.getMessage() for r in caplog.records] == ["mesh needed repair"], (
        "a cache hit swallowed the warning a fresh cook prints")


def test_cook_memo_misses_on_any_input_change_and_can_be_disabled(monkeypatch):
    calls = []

    def build():
        calls.append(1)
        return bytes([len(calls)])

    cook_memo.cached("texture", (b"a",), build)
    cook_memo.cached("texture", (b"b",), build)          # different bytes
    cook_memo.cached("model", (b"a",), build)            # different cooker
    cook_memo.cached("texture", (b"a", b""), build)      # different arity
    assert len(calls) == 4
    monkeypatch.setenv("RSMM_NO_COOK_CACHE", "1")
    cook_memo.cached("texture", (b"a",), build)
    assert len(calls) == 5, "--no-cache still served from the cache"


def _mod(tmp_path, monkeypatch, emits):
    """A mod whose content emit is a stub that counts its runs."""
    import rsmm.sdk.content as content

    root = tmp_path / "m"
    (root / "assets").mkdir(parents=True)
    (root / "art.glb").write_bytes(b"model")

    class _Reg:
        def __init__(self, **kw): pass
        def register(self, *a, **kw): pass
        def emit(self, out_dir):
            emits.append(1)
            logging.getLogger("rsmm.sdk.kinds.heros").warning("bone not on skeleton")
            p = out_dir / "out.gen"
            p.write_bytes(b"emitted")
            return [p]

    monkeypatch.setattr(content, "ContentRegistry", _Reg)
    return SimpleNamespace(id="m", enabled=True, experimental=False, root=root,
                           assets_dir=root / "assets",
                           content_blocks=[{"kind": "hero", "id": "x"}])


def test_unchanged_mod_is_not_re_emitted(tmp_path, monkeypatch, caplog):
    from rsmm.cli import apply_mods as A
    emits: list = []
    mod = _mod(tmp_path, monkeypatch, emits)
    A.emit_content_blocks([mod])
    with caplog.at_level(logging.WARNING, logger="rsmm"):
        A.emit_content_blocks([mod])
    assert len(emits) == 1, "an unchanged mod was emitted again"
    assert (mod.assets_dir / "out.gen").read_bytes() == b"emitted"
    assert "bone not on skeleton" in caplog.text, "a kept emit lost its warning"


@pytest.mark.parametrize("change", ["input file", "manifest block", "emitted file", "no-cache"])
def test_mod_is_re_emitted_when_anything_it_depends_on_changes(tmp_path, monkeypatch, change):
    from rsmm.cli import apply_mods as A
    emits: list = []
    mod = _mod(tmp_path, monkeypatch, emits)
    A.emit_content_blocks([mod])
    if change == "input file":
        (mod.root / "art.glb").write_bytes(b"model v2")
    elif change == "manifest block":
        mod.content_blocks[0]["name"] = "renamed"
    elif change == "emitted file":
        (mod.assets_dir / "out.gen").write_bytes(b"hand-edited")
    else:
        monkeypatch.setenv("RSMM_NO_COOK_CACHE", "1")
    A.emit_content_blocks([mod])
    assert len(emits) == 2, f"a changed {change} did not trigger a re-emit"


def test_loader_runtime_files_do_not_invalidate_the_emit(tmp_path, monkeypatch):
    from rsmm.cli import apply_mods as A
    emits: list = []
    mod = _mod(tmp_path, monkeypatch, emits)
    A.emit_content_blocks([mod])
    (mod.root / ".rsmm_state.json").write_text(json.dumps({"k": 1}))
    A.emit_content_blocks([mod])
    assert len(emits) == 1, "a file the loader writes during play re-emitted the mod"


def test_failed_emit_is_not_cached(tmp_path, monkeypatch):
    import rsmm.sdk.content as content
    from rsmm.cli import apply_mods as A
    emits: list = []
    mod = _mod(tmp_path, monkeypatch, emits)
    A.emit_content_blocks([mod])
    good = content.ContentRegistry

    class _Broken(good):
        def emit(self, out_dir):
            raise ValueError("boom")

    monkeypatch.setattr(content, "ContentRegistry", _Broken)
    (mod.root / "art.glb").write_bytes(b"broken model")
    A.emit_content_blocks([mod])
    assert not (mod.root / A._EMIT_CACHE).exists(), "a failed emit left a cache key"
    monkeypatch.setattr(content, "ContentRegistry", good)
    A.emit_content_blocks([mod])
    assert len(emits) == 2, "the emit after a failure was skipped"
