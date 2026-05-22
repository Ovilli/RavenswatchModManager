from __future__ import annotations


def test_linux_prefers_direct_steam_launch(monkeypatch):
    from rsmm.cli import run as run_mod

    calls: list[list[str]] = []

    monkeypatch.setattr(run_mod.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(run_mod, "_steam_root", lambda: None)
    monkeypatch.setattr(run_mod.shutil, "which", lambda name: "/usr/bin/steam" if name == "steam" else None)

    def fake_popen(args, stdout=None, stderr=None):
        calls.append(list(args))

        class _P:
            pass

        return _P()

    monkeypatch.setattr(run_mod.subprocess, "Popen", fake_popen)

    rc = run_mod._open_steam_url("steam://rungameid/2071280")

    assert rc == 0
    assert calls == [["steam", "-applaunch", "2071280"]]


def test_linux_uses_flatpak_spawn_host_when_available(monkeypatch):
    from rsmm.cli import run as run_mod

    calls: list[list[str]] = []

    monkeypatch.setattr(run_mod.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(run_mod, "_steam_root", lambda: None)

    def fake_which(name: str):
        if name == "steam":
            return None
        if name == "flatpak":
            return "/usr/bin/flatpak"
        if name == "flatpak-spawn":
            return "/usr/bin/flatpak-spawn"
        return None

    monkeypatch.setattr(run_mod.shutil, "which", fake_which)

    def fake_popen(args, stdout=None, stderr=None):
        calls.append(list(args))

        class _P:
            pass

        return _P()

    monkeypatch.setattr(run_mod.subprocess, "Popen", fake_popen)

    rc = run_mod._open_steam_url("steam://rungameid/2071280")

    assert rc == 0
    assert calls == [[
        "flatpak-spawn",
        "--host",
        "flatpak",
        "run",
        "com.valvesoftware.Steam",
        "-applaunch",
        "2071280",
    ]]