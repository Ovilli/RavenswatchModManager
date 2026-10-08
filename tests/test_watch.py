"""`rsmm watch`: what counts as an edit, and the lint gate in front of apply."""

from __future__ import annotations

import json
import signal

import pytest

from rsmm.cli import watch as W

_GOOD = (
    "[mod]\n"
    'id = "{id}"\n'
    'name = "{id}"\n'
    'version = "0.1.0"\n'
    'author = "someone"\n'
    "enabled = {enabled}\n"
)


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    d = tmp_path / "mods"
    d.mkdir()
    monkeypatch.setenv("RSMM_MODS_DIR", str(d))
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(W, "_ST", W._term.Style(enabled=False))
    return d


def _mod(mods, mod_id, *, enabled=True, lua="local R = require 'rsmm'\n"):
    root = mods / mod_id
    root.mkdir()
    (root / "manifest.toml").write_text(
        _GOOD.format(id=mod_id, enabled="true" if enabled else "false"),
        encoding="utf-8")
    (root / "init.lua").write_text(lua, encoding="utf-8")
    return root


def test_scan_skips_what_apply_and_editors_write(mods):
    root = _mod(mods, "A")
    (root / "assets").mkdir()
    (root / "assets" / "hand.png").write_bytes(b"x")
    (root / "assets" / "emitted.gen").write_bytes(b"x")
    (root / ".rsmm_emitted.json").write_text(json.dumps(["emitted.gen"]))
    (root / ".rsmm_emit_cache.json").write_text("{}")
    (root / ".init.lua.swp").write_bytes(b"x")
    (root / "init.lua~").write_bytes(b"x")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref")
    (mods / "_merged").mkdir()
    (mods / "_merged" / "manifest.toml").write_text("[mod]")

    seen = {p.replace("\\", "/").split("/mods/", 1)[1] for p in W._scan([mods])}
    assert seen == {"A/manifest.toml", "A/init.lua", "A/assets/hand.png"}


def test_changes_are_named_per_mod(mods):
    _mod(mods, "A")
    _mod(mods, "B")
    before = W._scan([mods])
    for name in ("one.lua", "two.lua", "three.lua", "four.lua"):
        (mods / "A" / name).write_text("--", encoding="utf-8")
    (mods / "B" / "init.lua").write_text("-- edited", encoding="utf-8")
    after = W._scan([mods])

    groups = W._by_mod(W._changed(before, after), mods)
    assert sorted(groups) == ["A", "B"]
    assert groups["B"] == ["init.lua"]
    text = W._describe(groups, mods)
    assert text.startswith("A (four.lua, one.lua, three.lua +1 more), B (init.lua)")


def test_a_deleted_mod_is_described_as_removed(mods):
    _mod(mods, "Gone")
    before = W._scan([mods])
    for p in sorted((mods / "Gone").iterdir()):
        p.unlink()
    (mods / "Gone").rmdir()
    groups = W._by_mod(W._changed(before, W._scan([mods])), mods)
    assert W._describe(groups, mods) == "Gone (removed)"


def test_lint_gate_blocks_a_half_saved_manifest(mods, capsys):
    root = _mod(mods, "A")
    (root / "manifest.toml").write_text('[mod]\nid = "A\n', encoding="utf-8")
    lines: list[str] = []
    assert W._lint_gate(["A"], mods, lines.append) == ["A"]
    out = capsys.readouterr().out
    assert "manifest parse" in out
    assert any("has 1 error(s)" in ln for ln in lines)


def test_lint_gate_prints_errors_but_not_warnings(mods, capsys):
    _mod(mods, "A", lua="local R = require 'rsmm'\nR.call_raw(0x140001000)\n")
    assert W._lint_gate(["A"], mods, lambda _m: None) == ["A"]
    out = capsys.readouterr().out
    assert "raw game address" in out
    assert "[WARN]" not in out
    assert "(raw=" not in out, "the per-mod summary row repeats the count"


def test_lint_gate_passes_clean_and_disabled_mods(mods, capsys):
    _mod(mods, "Clean")
    _mod(mods, "Off", enabled=False,
         lua="local R = require 'rsmm'\nR.call_raw(0x140001000)\n")
    assert W._lint_gate(["Clean", "Off"], mods, lambda _m: None) == []
    assert "raw game address" not in capsys.readouterr().out


def _run_watch(monkeypatch, tmp_path, edits, *argv):
    """Drive main()'s loop: each sleep at the poll interval performs the next
    scripted edit, and the loop ends when the script runs out."""
    game = tmp_path / "game"
    (game / W.COOKING_REL).mkdir(parents=True)
    applies: list[str] = []
    monkeypatch.setattr(W, "_run_apply",
                        lambda _g, _d, _log: applies.append("apply") or 0)
    monkeypatch.setattr(signal, "signal", lambda *_a: None)
    script = iter(edits)

    def fake_sleep(secs):
        if secs != 1.0:
            return                          # a settle pause, not a poll
        try:
            next(script)()
        except StopIteration:
            raise KeyboardInterrupt from None

    monkeypatch.setattr(W.time, "sleep", fake_sleep)
    monkeypatch.setattr("sys.argv", ["watch", "--game-dir", str(game),
                                     "--interval", "1", *argv])
    with pytest.raises(KeyboardInterrupt):
        W.main()
    return applies


def _touch(path, text):
    def edit():
        path.write_text(text, encoding="utf-8")
    return edit


def test_watch_applies_good_saves_and_holds_back_broken_ones(
        mods, tmp_path, monkeypatch, capsys):
    root = _mod(mods, "A")
    manifest = root / "manifest.toml"
    good = manifest.read_text(encoding="utf-8")
    applies = _run_watch(monkeypatch, tmp_path, [
        _touch(root / "init.lua", "-- tweak 1\n"),       # applied
        _touch(manifest, '[mod]\nid = "A\n'),            # held back
        _touch(manifest, good),                          # applied again
        lambda: None,                                    # nothing changed
    ])
    out = capsys.readouterr().out
    assert applies == ["apply", "apply", "apply"]       # initial + two saves
    assert "changed: A (init.lua)" in out
    assert "not applied" in out


def test_no_lint_applies_regardless(mods, tmp_path, monkeypatch, capsys):
    root = _mod(mods, "A")
    applies = _run_watch(monkeypatch, tmp_path, [
        _touch(root / "manifest.toml", '[mod]\nid = "A\n'),
    ], "--no-lint")
    assert applies == ["apply", "apply"]
    assert "not applied" not in capsys.readouterr().out


def test_apply_bookkeeping_does_not_trigger_another_apply(
        mods, tmp_path, monkeypatch):
    root = _mod(mods, "A")

    def apply_writes_its_own_files():
        (root / "assets").mkdir(exist_ok=True)
        (root / "assets" / "out.gen").write_bytes(b"emitted")
        (root / ".rsmm_emitted.json").write_text(json.dumps(["out.gen"]))
        (root / ".rsmm_emit_cache.json").write_text("{}")
        (mods / "_merged").mkdir(exist_ok=True)
        (mods / "_merged" / "manifest.toml").write_text("[mod]")

    applies = _run_watch(monkeypatch, tmp_path, [apply_writes_its_own_files])
    assert applies == ["apply"]


def test_watch_refuses_to_start_without_a_game(mods, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["watch", "--game-dir", str(tmp_path / "nope")])
    assert W.main() == 1
    assert "no Ravenswatch install" in capsys.readouterr().err
