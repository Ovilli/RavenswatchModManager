"""Internal: execute a mod lifecycle hook script in a child rsmm process.

Not a user-facing subcommand — `_dispatch.main` routes the reserved
``__on-disable`` verb here and it appears in no help text or docs
inventory.

It exists because of PyInstaller. `on_disable.py` is a plain Python file
that has to run in its own process (a mod's cleanup must not be able to
take the CLI down with it, and it needs a timeout). In a source checkout
`sys.executable` is a Python interpreter, so spawning
``[sys.executable, "on_disable.py"]`` works. In the FROZEN sidecar — which
is what every desktop user runs — `sys.executable` IS the rsmm binary and
there is no interpreter on disk to hand the script to, so that same argv
becomes ``rsmm on_disable.py``: an unknown subcommand that exits 2 without
running a line of the hook. Every mod's cleanup silently did nothing in
the desktop app while looking like it had run.

So the frozen path re-invokes rsmm itself (`self_cmd`) with this verb and
runs the script through `runpy` on the bundled interpreter. Same process
isolation, same timeout, same env contract as the source path.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

#: The verb `_dispatch.main` reserves for this module. Dunder-prefixed so it
#: reads as internal and cannot collide with a real subcommand.
VERB = "__on-disable"

#: Hooks are the only thing this runner will execute. A mod directory is
#: attacker-controlled content; without the name check this verb would be a
#: general "run any Python file" primitive reachable from the CLI surface.
ALLOWED_NAMES = frozenset({"on_disable.py"})


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print(f"usage: rsmm {VERB} <path-to-hook.py>", file=sys.stderr)
        return 2

    script = Path(argv[0])
    if script.name not in ALLOWED_NAMES:
        print(f"refusing to run {script.name}: not a mod lifecycle hook",
              file=sys.stderr)
        return 2
    if not script.is_file():
        print(f"no such hook: {script}", file=sys.stderr)
        return 2

    # The hook is written as a standalone script — it ends in
    # `if __name__ == "__main__": sys.exit(main())`, so it must see
    # `__main__` or its body never executes. `sys.argv[0]` is set to the
    # script for the same reason.
    sys.argv = [str(script)]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
