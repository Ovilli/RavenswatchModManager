"""rsmm install-loader — copy winhttp.dll + SDK lib into the game install."""

from __future__ import annotations

import subprocess
import sys

from rsmm.engine.paths import COOKING_SUBDIR, DEFAULT_GAME_DIR, REPO_ROOT


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        if (DEFAULT_GAME_DIR / COOKING_SUBDIR).is_dir():
            argv = [str(DEFAULT_GAME_DIR)]
        else:
            print(
                "Could not autodetect Ravenswatch install. "
                "Pass the path: rsmm install-loader <game-dir>",
                file=sys.stderr,
            )
            return 1

    # Use REPO_ROOT so this works under both a source checkout and a
    # PyInstaller-frozen bundle (where REPO_ROOT resolves to _MEIPASS
    # and the install_loader scripts must be bundled alongside it).
    root = REPO_ROOT
    script_sh = root / "src/rsmm/cli/install_loader.sh"
    script_ps1 = root / "src/rsmm/cli/install_loader.ps1"

    if sys.platform == "win32":
        if not script_ps1.exists():
            print(f"install script not found: {script_ps1}", file=sys.stderr)
            return 1
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(script_ps1), *argv]
        return subprocess.call(cmd)

    if not script_sh.exists():
        print(f"install script not found: {script_sh}", file=sys.stderr)
        return 1
    return subprocess.call([str(script_sh), *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
