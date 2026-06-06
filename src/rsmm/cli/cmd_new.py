"""rsmm new — scaffold a mod directory."""

from __future__ import annotations

import re
import sys

from rsmm.engine.paths import MODS_DIR

try:
    from rsmm.sdk.content import kind_confidence
except ImportError:  # pragma: no cover - SDK always present in practice
    def kind_confidence(_k: str) -> str:
        return "guess"

_CONTENT_KINDS = ("item", "talent", "enemy", "boss", "map", "hero")

#: Per-kind seed for the `[[content]]` block — extra manifest lines beyond
#: the common id/base/name/description. Keeps scaffolds concrete so a fresh
#: `rsmm new <id> --kind X` lints clean and points at real next steps.
_KIND_FIELDS: dict[str, list[str]] = {
    "item": [
        'icon          = "GreenArmor"          # vanilla icon id, or assets/<file>.png',
        'value_patches = [["Armor per Object Value", 2.0, 99.0]]  # [label, old, new]',
    ],
    "enemy": [
        '# tribe       = "Gnolls"              # optional: repoint tribe_ref',
        '# add_flags   = ["Elite"]             # optional: extend base tag list',
    ],
    "hero": [
        '# Reskinning an existing hero works today; a brand-new roster slot',
        '# is blocked on the hero-library singleton + roster detour.',
    ],
    "map": [],
    "boss": [
        '# WARNING: boss byte layout is a guess — expect rejection/crash',
        '# until the picker/HP/arena offsets are RE-confirmed.',
    ],
}

#: Suggested vanilla base ids per kind, so the placeholder is actionable.
_KIND_BASE_HINT: dict[str, str] = {
    "item": "Armor_Per_Object",
    "enemy": "Gnoll_Shielded",
    "hero": "Sun_Priest",
    "map": "<vanilla map id>",
    "boss": "BabaYaga",
}
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

    # Non-confirmed kinds must opt into [mod] experimental = true (the lint
    # confidence gate rejects them otherwise) and ship disabled by default so
    # a scaffolded experimental/guess mod doesn't auto-apply unverified bytes.
    conf = kind_confidence(kind) if kind else "confirmed"
    experimental = conf != "confirmed"

    manifest = [
        "[mod]",
        f'id          = "{mod_id}"',
        f'name        = "{mod_id}"',
        'version     = "0.1.0"',
        'author      = "you"',
        'description = ""',
        f"enabled     = {'false' if experimental else 'true'}",
        'sdk_version = ">=3.0,<4"',
    ]
    if experimental:
        manifest.append(
            f"experimental = true            # kind {kind!r} is {conf!r}, "
            "not verified in-game")
    if kind == "talent":
        # Talent edits a vanilla hero entity in place — no base clone, no
        # name/description; it keys off `hero` + `value_patches`.
        manifest += [
            "",
            f"# kind {kind!r} confidence: {conf}",
            "[[content]]",
            'kind          = "talent"',
            'hero          = "Juliet"             # EntitySettings/Heroes/Hero_<hero>',
            'value_patches = [["<talent label>", 0.0, 0.0]]  # [label, old, new]',
        ]
    elif kind:
        manifest += [
            "",
            f"# kind {kind!r} confidence: {conf}",
            "[[content]]",
            f'kind          = "{kind}"',
            f'id            = "{mod_id}_{kind}_1"',
            f'base          = "{_KIND_BASE_HINT.get(kind, "<vanilla id to clone>")}"',
            f'name          = "{mod_id} sample {kind}"',
            'description   = ""',
        ]
        manifest += _KIND_FIELDS.get(kind, [])
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
    print(f"Created {target}" + (f" (kind={kind}, confidence={conf})" if kind else ""))
    if experimental:
        print(f"  ! kind {kind!r} is {conf!r}: emitted bytes are NOT verified "
              "in-game. Scaffolded with experimental = true and enabled = "
              "false. Flip enabled once you've confirmed it loads.")
    print("Next: edit init.lua + manifest.toml, then `rsmm apply`.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
