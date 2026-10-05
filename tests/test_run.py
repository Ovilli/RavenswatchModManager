from __future__ import annotations


def test_linux_prefers_direct_steam_launch(monkeypatch):
    from rsmm.cli import run as run_mod

    calls: list[list[str]] = []

    monkeypatch.setattr(run_mod.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(run_mod, "_steam_root", lambda: None)
    monkeypatch.setattr(
        run_mod.shutil,
        "which",
        lambda name: "/usr/bin/steam" if name == "steam" else None,
    )

    def fake_popen(args, **_kw):
        calls.append(list(args))

        class _P:
            def wait(self, timeout=None):
                return 0  # handed off to Steam

        return _P()

    monkeypatch.setattr(run_mod.subprocess, "Popen", fake_popen)

    rc = run_mod._open_steam_url("steam://rungameid/2071280")

    assert rc == 0
    assert calls == [["steam", "-applaunch", "2071280"]]


def test_linux_uses_flatpak_spawn_host_when_sandboxed(monkeypatch):
    """`flatpak-spawn --host` only works from INSIDE a flatpak sandbox."""
    from rsmm.cli import run as run_mod

    calls: list[list[str]] = []

    monkeypatch.setattr(run_mod.sys, "platform", "linux", raising=False)
    real_exists = run_mod.Path.exists
    monkeypatch.setattr(
        run_mod.Path, "exists",
        lambda self: str(self) == "/.flatpak-info" or real_exists(self))
    # The sandbox's own `flatpak` cannot reach the host's Steam.
    monkeypatch.setattr(run_mod, "_spawn_launcher",
                        lambda argv: calls.append(argv) or (None if argv[0] == "flatpak-spawn"
                                                            else "exit 1"))
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

    rc = run_mod._open_steam_url("steam://rungameid/2071280")

    assert rc == 0
    assert calls[-1] == [
        "flatpak-spawn",
        "--host",
        "flatpak",
        "run",
        "com.valvesoftware.Steam",
        "-applaunch",
        "2071280",
    ]
