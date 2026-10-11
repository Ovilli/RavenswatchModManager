"""`rsmm editor` — items, talents, abilities and maps in one local page.

    rsmm editor                      open on the Items tab
    rsmm editor --tab map            ...or on another tab
    rsmm editor --port 9000 --no-browser

``item-editor``, ``talent-editor``, ``ability-editor`` and ``map-editor`` are
aliases that open it on their tab (see ``_dispatch.LEGACY``). The editors live
in ``rsmm.cli.editor``.
"""

from __future__ import annotations

import sys

from rsmm.cli.editor.server import run


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
