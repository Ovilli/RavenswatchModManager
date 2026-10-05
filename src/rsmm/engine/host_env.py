"""An environment fit for launching the HOST's own programs (Steam, flatpak, xdg-open).

Under the desktop AppImage, rsmm inherits an environment rewritten to point
inside the AppDir: `LD_LIBRARY_PATH` at the AppImage's bundled libraries (built
on Ubuntu 22.04), plus linuxdeploy's GTK hook (`GTK_PATH`, `GIO_EXTRA_MODULES`,
`GSETTINGS_SCHEMA_DIR`, ...) and `PYTHONHOME`. A host program started with that
loads the AppImage's old GLib against the system's newer libraries and dies at
once. Measured 2026-10-05 on Debian 13: `flatpak` exited 127 with
``symbol lookup error: libmalcontent-0.so.0: undefined symbol:
g_task_set_static_name`` - so "Launch" in the desktop app started neither Steam
nor the game, and reported success, because the child's output went nowhere.

The desktop's own folder-reveal hit the same thing (see
`apps/desktop/src-tauri/src/profile_dir.rs::reveal`); this is the Python side.
"""

from __future__ import annotations

import os
import sys

#: Set by the AppImage runtime, linuxdeploy's hooks, or the frozen sidecar, and
#: meaningful only to programs inside the AppDir / bundle.
_BUNDLE_ONLY_VARS = (
    "LD_LIBRARY_PATH",
    "LD_LIBRARY_PATH_ORIG",
    "LD_PRELOAD",
    "GTK_DATA_PREFIX",
    "GTK_EXE_PREFIX",
    "GTK_PATH",
    "GTK_IM_MODULE_FILE",
    "GTK_THEME",
    "GDK_PIXBUF_MODULE_FILE",
    "GDK_BACKEND",
    "GSETTINGS_SCHEMA_DIR",
    "GIO_EXTRA_MODULES",
    "GIO_MODULE_DIR",
    "GI_TYPELIB_PATH",
    "GST_PLUGIN_PATH_1_0",
    "GST_PLUGIN_SYSTEM_PATH",
    "GST_PLUGIN_SYSTEM_PATH_1_0",
    "GST_PLUGIN_SCANNER_1_0",
    "GST_PTP_HELPER_1_0",
    "GST_REGISTRY_REUSE_PLUGIN_SCANNER",
    "PYTHONHOME",
    "PYTHONPATH",
    "PERLLIB",
    "QT_PLUGIN_PATH",
)

#: Path-list variables the AppImage PREFIXES with AppDir entries; the host's own
#: entries are still in there, so only the AppDir ones are dropped.
_PATH_LISTS = ("PATH", "XDG_DATA_DIRS")


def _bundled() -> bool:
    return bool(os.environ.get("APPDIR") or os.environ.get("APPIMAGE")
                or getattr(sys, "frozen", False))


def host_env(base: dict[str, str] | None = None) -> dict[str, str] | None:
    """The environment to hand a host program, or None to inherit unchanged.

    Outside an AppImage or frozen bundle this returns None: a developer's own
    `LD_LIBRARY_PATH` is theirs, and running from source has nothing to undo.
    """
    env = dict(os.environ if base is None else base)
    if not (env.get("APPDIR") or env.get("APPIMAGE") or (base is None and _bundled())):
        return None
    appdir = env.get("APPDIR", "")
    meipass = getattr(sys, "_MEIPASS", "")
    for var in _BUNDLE_ONLY_VARS:
        env.pop(var, None)
    roots = tuple(r.rstrip("/") for r in (appdir, meipass) if r)
    for var in _PATH_LISTS:
        if var not in env or not roots:
            continue
        kept = [p for p in env[var].split(os.pathsep)
                if p and not any(p == r or p.startswith(r + "/") for r in roots)]
        if var == "PATH" and not kept:
            kept = ["/usr/local/bin", "/usr/bin", "/bin"]
        env[var] = os.pathsep.join(kept)
    return env
