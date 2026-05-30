"""
Single-binary launcher entry point for Ravenswatch Mod Manager.

Frozen-bundle equivalent of the `./rsmm` script: it puts `rsmm` on the
import path, initialises logging, then hands every invocation to the one
canonical dispatcher (`rsmm.cli._dispatch`). Keeping a single router here
avoids the drift that a duplicated subcommand table accumulates — the GUI,
for instance, has moved out of the CLI into the Tauri desktop app, and the
dispatcher already reports that for `gui`.

Works for both a source checkout (`python3 launcher.py …`) and a
PyInstaller build (`./RavenswatchModManager …`).
"""

from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_path() -> None:
    """Make `import rsmm.*` resolvable from the repo OR a frozen bundle.

    Source mode: prepend `<repo>/src` (mirrors the `./rsmm` script).
    Frozen mode: PyInstaller already extracts to sys._MEIPASS and sets up
    sys.path, so we do nothing.
    """
    if getattr(sys, "frozen", False):
        return
    src = Path(__file__).resolve().parent / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def main(argv: list[str] | None = None) -> int:
    _bootstrap_path()

    # Initialise logging early so downstream imports get a configured root.
    try:
        from rsmm.logging import setup_logging
        setup_logging()
    except Exception:  # noqa: BLE001 - logging is best-effort, never fatal
        pass

    args = sys.argv[1:] if argv is None else argv

    from rsmm.cli import _dispatch
    return int(_dispatch.main(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
