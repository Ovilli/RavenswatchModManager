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
        lambda self: self.as_posix() in ("/.flatpak-info", "\\.flatpak-info") or real_exists(self))
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


def test_set_launch_options_no_launch_does_not_apply_mods(monkeypatch, tmp_path):
    """The repair-only path must not apply mods: nothing would restore them."""
    from rsmm.cli import run as run_mod

    sub_calls: list[list[str]] = []
    written: list[str] = []
    vdf = tmp_path / "localconfig.vdf"
    vdf.write_text("")

    monkeypatch.setattr(run_mod.sys, "platform", "linux", raising=False)
    monkeypatch.setattr(run_mod.sys, "argv", ["rsmm run", "--set-launch-options", "--no-launch"])
    monkeypatch.setattr(run_mod, "_rsmm_subcommand", lambda a: sub_calls.append(a) or True)
    monkeypatch.setattr(run_mod, "find_game_dir",
                        lambda: (_ for _ in ()).throw(AssertionError("loader install ran")))
    monkeypatch.setattr(run_mod, "_steam_root", lambda: tmp_path)
    monkeypatch.setattr(run_mod, "_localconfig_paths", lambda _root: [vdf])
    monkeypatch.setattr(run_mod, "_read_launch_options", lambda *_a: "")
    monkeypatch.setattr(run_mod, "_is_steam_running", lambda: False)
    monkeypatch.setattr(run_mod, "_write_launch_options",
                        lambda _p, _id, v: written.append(v) or True)
    monkeypatch.setattr(run_mod, "_open_steam_url",
                        lambda _u: (_ for _ in ()).throw(AssertionError("launched")))

    assert run_mod.main() == 0
    assert sub_calls == []
    assert written == [run_mod.RECOMMENDED_LAUNCH_OPTIONS]


_REG = (
    "WINE REGISTRY Version 2\n"
    ";; All keys relative to REGISTRY\\\\User\\\\S-1-5-21-0-0-1000-1000\n\n"
    "#arch=win64\n\n"
    "[Software\\\\Wine\\\\DllOverrides] 1774238072\n"
    "#time=1dcba78c213f514\n"
    '"atl100"="native,builtin"\n'
    '"winhttp"="builtin"\n'
    "\n"
    "[Software\\\\Wine\\\\Fonts] 1774238072\n"
    '"x"="y"\n'
)


def _prefix(tmp_path, reg_text):
    from rsmm.cli import run as run_mod
    game = tmp_path / "steamapps" / "common" / "Ravenswatch"
    game.mkdir(parents=True)
    reg = run_mod.prefix_user_reg(game)
    if reg_text is not None:
        reg.parent.mkdir(parents=True)
        reg.write_text(reg_text)
    return game, reg


def test_prefix_override_replaces_builtin_entry_in_section(monkeypatch, tmp_path):
    from rsmm.cli import run as run_mod
    monkeypatch.setattr(run_mod, "_prefix_in_use", lambda _p: False)
    game, reg = _prefix(tmp_path, _REG)

    assert not run_mod.prefix_override_present(reg)
    assert run_mod.ensure_prefix_override(game)
    text = reg.read_text()
    section = text.split("[Software\\\\Wine\\\\DllOverrides]")[1].split("\n[")[0]
    assert section.splitlines()[1:3] == ["#time=1dcba78c213f514", '"winhttp"="native,builtin"']
    assert '"winhttp"="builtin"' not in text
    assert '"x"="y"' in text  # other sections untouched
    assert reg.with_name("user.reg.rsmm.bak").read_text() == _REG
    assert run_mod.ensure_prefix_override(game)  # idempotent
    assert reg.read_text() == text


def test_prefix_override_appends_missing_section(monkeypatch, tmp_path):
    from rsmm.cli import run as run_mod
    monkeypatch.setattr(run_mod, "_prefix_in_use", lambda _p: False)
    game, reg = _prefix(tmp_path, "WINE REGISTRY Version 2\n\n#arch=win64\n")
    assert run_mod.ensure_prefix_override(game)
    assert run_mod.prefix_override_present(reg)


def test_prefix_override_skips_missing_or_live_prefix(monkeypatch, tmp_path):
    from rsmm.cli import run as run_mod
    game, _reg = _prefix(tmp_path / "a", None)
    assert not run_mod.ensure_prefix_override(game)  # never run under Proton

    monkeypatch.setattr(run_mod, "_prefix_in_use", lambda _p: True)
    game, reg = _prefix(tmp_path / "b", _REG)
    assert not run_mod.ensure_prefix_override(game)  # wineserver would clobber it
    assert reg.read_text() == _REG


def test_windows_launch_never_touches_proton_prefix(monkeypatch):
    """Native Windows loads winhttp.dll from the game dir: no override, no prefix."""
    from rsmm.cli import run as run_mod

    opened: list[str] = []
    monkeypatch.setattr(run_mod.sys, "platform", "win32", raising=False)
    monkeypatch.setattr(run_mod.sys, "argv", ["rsmm run"])
    monkeypatch.setattr(run_mod, "find_game_dir", lambda: None)
    monkeypatch.setattr(run_mod, "_rsmm_subcommand", lambda _a: True)
    monkeypatch.setattr(run_mod, "ensure_prefix_override",
                        lambda _g: (_ for _ in ()).throw(AssertionError("prefix touched")))
    monkeypatch.setattr(run_mod, "_steam_root",
                        lambda: (_ for _ in ()).throw(AssertionError("vdf checked")))
    monkeypatch.setattr(run_mod, "_open_steam_url", lambda u: opened.append(u) or 0)

    assert run_mod.main() == 0
    assert opened == ["steam://rungameid/2071280"]
