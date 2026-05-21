"""rsmm new — scaffold a mod directory."""

from __future__ import annotations

import re
import sys

from rsmm.engine.paths import MODS_DIR

_CONTENT_KINDS = ("item", "enemy", "boss", "map", "hero")
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_USAGE = (
    f"usage: rsmm new <id> [--kind {'|'.join(_CONTENT_KINDS)}]\n"
    "\n"
    "Scaffold a new mod directory under mods/<id>/.\n"
    "\n"
    "  <id>         mod identifier ([A-Za-z][A-Za-z0-9_-]*, up to 64 chars)\n"
    f"  --kind KIND  also seed a [[content]] block; one of {', '.join(_CONTENT_KINDS)}\n"
)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    kind: str | None = None
    args: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(_USAGE)
            return 0
        if a == "--kind":
            i += 1
            if i >= len(argv):
                print("--kind takes a value", file=sys.stderr)
                return 2
            kind = argv[i]
        elif a.startswith("--kind="):
            kind = a.split("=", 1)[1]
        else:
            args.append(a)
        i += 1
    if len(args) != 1:
        print(_USAGE, file=sys.stderr)
        return 2
    if kind is not None and kind not in _CONTENT_KINDS:
        print(f"--kind must be one of: {', '.join(_CONTENT_KINDS)}",
              file=sys.stderr)
        return 2
    mod_id = args[0]
    if not _ID_RE.match(mod_id):
        print(f"invalid mod id: {mod_id!r} (must match {_ID_RE.pattern})",
              file=sys.stderr)
        return 2
    target = MODS_DIR / mod_id
    if target.exists():
        print(f"mod already exists: {target}", file=sys.stderr)
        return 1
    (target / "assets").mkdir(parents=True)

    manifest = [
        "[mod]",
        f'id          = "{mod_id}"',
        f'name        = "{mod_id}"',
        'version     = "0.1.0"',
        'author      = "you"',
        'description = ""',
        "enabled     = true",
        'sdk_version = ">=3.0,<4"',
    ]
    if kind:
        manifest += [
            "",
            "[[content]]",
            f'kind        = "{kind}"',
            f'id          = "{mod_id}_{kind}_1"',
            'base        = "<vanilla id to clone>"',
            f'name        = "{mod_id} sample {kind}"',
            'description = ""',
        ]
    (target / "manifest.toml").write_text("\n".join(manifest) + "\n",
                                          encoding="utf-8")

    (target / "init.lua").write_text(
        '-- ' + mod_id + ' — see docs/MODDING.md for the SDK reference.\n'
        '\n'
        'local R = require "rsmm"\n'
        'R.health.checkpoint("per_mod:' + mod_id + '")\n'
        '\n'
        'R.on("ready", function()\n'
        '    R.log("[' + mod_id + '] loaded")\n'
        'end)\n',
        encoding="utf-8",
    )
    (target / "config_schema.toml").write_text(
        '# Optional: declare typed config fields here.\n'
        '# [fields.example]\n'
        '# type    = "bool"\n'
        '# default = true\n',
        encoding="utf-8",
    )
    (target / "lang").mkdir()
    (target / "lang" / "EN.toml").write_text(
        '[strings]\n'
        f'name = "{mod_id}"\n',
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {mod_id}\n\nDescribe your mod here.\n", encoding="utf-8",
    )
    print(f"Created {target}" + (f" (kind={kind})" if kind else ""))
    print("Next: edit init.lua + manifest.toml, then `rsmm apply`.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
