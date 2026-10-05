"""Launching host programs from inside the desktop AppImage."""

from __future__ import annotations

import sys

import pytest

from rsmm.cli import run
from rsmm.engine.host_env import host_env

APPDIR = "/tmp/.mount_RavensXYZ"

APPIMAGE_ENV = {
    "APPDIR": APPDIR,
    "APPIMAGE": "/home/u/Applications/RavenswatchModManager.AppImage",
    "LD_LIBRARY_PATH": f"{APPDIR}/usr/lib/:{APPDIR}/usr/lib/x86_64-linux-gnu/",
    "GTK_PATH": f"{APPDIR}//usr/lib/gtk-3.0",
    "GIO_EXTRA_MODULES": f"{APPDIR}/usr/lib/gio/modules",
    "GSETTINGS_SCHEMA_DIR": f"{APPDIR}//usr/share/glib-2.0/schemas",
    "GDK_BACKEND": "x11",
    "PYTHONHOME": f"{APPDIR}/usr/",
    "PATH": f"{APPDIR}/usr/bin/:{APPDIR}/usr/sbin/:/usr/local/bin:/usr/bin",
    "XDG_DATA_DIRS": f"{APPDIR}/usr/share:/usr/share:/usr/local/share",
    "HOME": "/home/u",
    "DISPLAY": ":0",
}


def test_appimage_library_and_gtk_overrides_are_removed():
    # These made host `flatpak` load the AppImage's old GLib and exit 127
    # ("undefined symbol: g_task_set_static_name"), so Launch did nothing.
    env = host_env(APPIMAGE_ENV)

    for var in ("LD_LIBRARY_PATH", "GTK_PATH", "GIO_EXTRA_MODULES",
                "GSETTINGS_SCHEMA_DIR", "GDK_BACKEND", "PYTHONHOME"):
        assert var not in env, var


def test_path_lists_keep_only_the_host_entries():
    env = host_env(APPIMAGE_ENV)

    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["XDG_DATA_DIRS"] == "/usr/share:/usr/local/share"


def test_everything_else_is_passed_through():
    env = host_env(APPIMAGE_ENV)

    assert env["HOME"] == "/home/u"
    assert env["DISPLAY"] == ":0"


def test_outside_a_bundle_the_environment_is_inherited(monkeypatch):
    # A developer's own LD_LIBRARY_PATH is theirs; there is nothing to undo.
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert host_env({"LD_LIBRARY_PATH": "/opt/mine", "PATH": "/usr/bin"}) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX launchers")
def test_a_launcher_that_dies_at_once_is_reported_not_called_a_success():
    why = run._spawn_launcher(["sh", "-c", "echo 'symbol lookup error' >&2; exit 127"])

    assert why == "exit 127: symbol lookup error"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX launchers")
def test_a_launcher_that_hands_off_and_exits_is_a_success():
    assert run._spawn_launcher(["true"]) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX launchers")
def test_a_launcher_that_keeps_running_is_a_success(monkeypatch):
    # With Steam closed, `flatpak run ... -applaunch` becomes Steam itself.
    monkeypatch.setattr(run, "_LAUNCHER_GRACE_S", 0.2)
    assert run._spawn_launcher(["sleep", "5"]) is None


def test_a_missing_program_is_reported():
    assert run._spawn_launcher(["rsmm-no-such-launcher-xyz"]) is not None


@pytest.mark.skipif(sys.platform == "win32", reason="Linux path")
def test_a_broken_launcher_falls_through_to_the_next(monkeypatch, capsys):
    monkeypatch.setattr(run, "_linux_launchers", lambda _a, _u: [["false"], ["true"]])

    assert run._open_steam_url("steam://rungameid/2071280") == 0
    assert "trying the next way" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="Linux path")
def test_when_every_launcher_fails_the_launch_fails(monkeypatch, capsys):
    monkeypatch.setattr(run, "_linux_launchers", lambda _a, _u: [["false"]])

    assert run._open_steam_url("steam://rungameid/2071280") == 1
    assert "Could not start Steam" in capsys.readouterr().err
