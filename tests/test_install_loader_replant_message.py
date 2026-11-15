"""install-loader says loudly when the channel replant overwrites a dev build.

The platform script plants this build's own DLL first; `_replant_newer_loader`
then plants the cached channel build over it. A stamped (channel) DLL being
replaced by a newer one is routine. An unstamped one is a local dev build, and
the tester must be told their changes are not in the game.
"""
from __future__ import annotations

from rsmm.cli import install_loader as il
from rsmm.engine import loader_update as lu


def _run(monkeypatch, tmp_path, capsys, prebuilt):
    monkeypatch.setattr(lu, "replant_cached",
                        lambda g: {"loader_version": 58, "planted": ["a", "b"]})
    monkeypatch.setattr(lu, "bundled_loader_dll", lambda: tmp_path / "winhttp.dll")
    monkeypatch.setattr(lu, "prebuilt_version", lambda dll: prebuilt)
    il._replant_newer_loader(tmp_path)
    return capsys.readouterr()


def test_replant_over_a_dev_build_warns(monkeypatch, tmp_path, capsys):
    out = _run(monkeypatch, tmp_path, capsys, None)
    assert "warning: replaced the loader you just installed (dev build, unstamped)" in out.err
    assert "channel loader v58" in out.err
    assert "local loader changes are not in the game" in out.err
    assert "—" not in out.err


def test_replant_over_an_older_channel_build_stays_neutral(monkeypatch, tmp_path, capsys):
    out = _run(monkeypatch, tmp_path, capsys, 57)
    assert "warning" not in (out.out + out.err)
    assert "replanted loader v58 from the update channel, over v57" in out.out
