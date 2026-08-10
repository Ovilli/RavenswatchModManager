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

_CONTENT_KINDS = ("item", "talent", "enemy", "boss", "map", "hero", "poi")

#: Per-kind seed for the `[[content]]` block — extra manifest lines beyond
#: the common id/base/name/description. Keeps scaffolds concrete so a fresh
#: `rsmm new <id> --kind X` lints clean and points at real next steps.
#:
#: `item` is absent on purpose: its block is mined from the chosen base by
#: :func:`_item_content_lines`, because a templated `value_patches` line is
#: wrong for every base but the one it was copied from.
_KIND_FIELDS: dict[str, list[str]] = {
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

#: Kinds scaffolded as a FOLDER rather than a `[[content]]` block. The manifest
#: should describe the mod, not accumulate one table per thing in it — see
#: :mod:`rsmm.sdk.discovery`. `talent` and `item` stay inline for now: talent
#: keys off the hero entity rather than an id, and the item block is mined from
#: its base, so neither is a plain "fields in a file" case yet.
_FOLDER_SEED: dict[str, list[str]] = {
    "poi": [
        "# A point of interest / structure. Drop `model.glb` + `albedo.png`,",
        "# `mra.png`, `normal.png` next to this file to make it your OWN art;",
        "# with no art it is a clone of the preset's shipped tile.",
        "#",
        "# Everything not set here comes from the preset: which tile it stands",
        "# in, which object it replaces, and which prop/material it inherits",
        "# structure from. `rsmm poi` browses what else is available.",
        'chapters = ["Dark_Hills", "Avalon", "Storm_Island"]',
        '# preset = "clearing"',
        '# weight = 0.15',
        '# kinds  = ["Fountain"]',
        '# icon   = "MiniMap\\Icons\\Map_Icons_Crow_Mark.png"',
    ],
    "enemy": [
        '# tribe     = "Gnolls"             # optional: repoint tribe_ref',
        '# add_flags = ["Elite"]            # optional: extend base tag list',
    ],
    "hero": [
        "# Reskinning an existing hero works today; a brand-new roster slot is",
        "# blocked on the hero-library singleton + roster detour.",
    ],
    "map": [],
    "boss": [
        "# WARNING: boss byte layout is a guess — expect rejection/crash until",
        "# the picker/HP/arena offsets are RE-confirmed.",
    ],
}
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_USAGE = (
    f"usage: rsmm new <id> [--kind {'|'.join(_CONTENT_KINDS)}] [--base ID]\n"
    "                     [--name TEXT] [--desc TEXT] [--icon ID] [--rarity R]\n"
    "\n"
    "Scaffold a new mod directory under mods/<id>/.\n"
    "\n"
    "  <id>         mod identifier ([A-Za-z][A-Za-z0-9_-]*, up to 64 chars)\n"
    f"  --kind KIND  also seed a [[content]] block; one of {', '.join(_CONTENT_KINDS)}\n"
    "  --base ID    vanilla id to clone (`rsmm items list` for kind=item).\n"
    "               For kind=item this reads the real base and seeds its\n"
    "               icon, rarity and every editable value field with its\n"
    "               true default, so the scaffold applies as-is.\n"
    "  --name TEXT  display name for the content (default: derived from <id>)\n"
    "  --desc TEXT  description shown in-game\n"
    "  --icon ID    vanilla icon stem (`rsmm items icons`) or assets/<file>.png\n"
    "  --rarity R   Common|Rare|Epic|Legendary|Cursed|Powerups (default: the\n"
    "               base item's own rarity)\n"
    "\n"
    "With --kind item and no --base, an interactive picker lists the vanilla\n"
    "items to clone. Piped or redirected, it falls back to a placeholder base.\n"
)

#: Cap on how many search hits the interactive base picker prints at once.
_PICK_LIMIT = 20


def _toml_str(value: str) -> str:
    """Quote a value as TOML, backslashes intact.

    Cooked asset references are Windows paths (``Objects\\UI_Object_X.png``),
    and in a TOML *basic* string ``\\U`` starts a unicode escape — emitting one
    raw produced a manifest that no longer parsed. A literal (single-quoted)
    string takes no escapes at all, which is exactly what these need.
    """
    text = str(value)
    if "'" not in text:
        return f"'{text}'"
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _interactive() -> bool:
    """True when both ends are a terminal, so prompting is safe.

    `rsmm new` is scripted (CI, the desktop sidecar) as often as it's typed;
    prompting a pipe would hang it.
    """
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - detached stdio
        return False


def _pick_base() -> str | None:
    """Search-and-pick a vanilla magical object. None if the user backs out."""
    from rsmm.cli import cmd_items
    items = [(iid, rarity) for iid, rarity, _ in cmd_items._iter_items()]
    if not items:
        print("  (no vanilla item corpus — run scripts/extract_uncooked.py)")
        return None
    print(f"\n{len(items)} vanilla items available to clone.")
    while True:
        try:
            needle = input("  search (blank = list all, q = skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if needle.lower() == "q":
            return None
        hits = [r for r in items if not needle or needle.lower() in r[0].lower()]
        if not hits:
            print("  no match — try a shorter search")
            continue
        for n, (iid, rarity) in enumerate(hits[:_PICK_LIMIT], 1):
            print(f"  {n:>2}. [{rarity:>10}] {iid}")
        if len(hits) > _PICK_LIMIT:
            print(f"  … and {len(hits) - _PICK_LIMIT} more — narrow the search")
        try:
            sel = input("  pick a number (blank = search again): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not sel:
            continue
        if sel.isdigit() and 1 <= int(sel) <= min(len(hits), _PICK_LIMIT):
            return hits[int(sel) - 1][0]
        print("  not one of the listed numbers")


def _item_content_lines(mod_id: str, base: str | None, name: str | None,
                        desc: str | None, icon: str | None,
                        rarity: str | None,
                        ) -> tuple[list[str], list[str], str | None]:
    """Build the item `[[content]]` block, mined from the real base.

    Returns (manifest lines, notes to print, resolved base id or None).

    When the base resolves we read its cooked bytes for the icon, the rarity
    and every editable value field with its true default — a scaffold whose
    `value_patches` were copied from another item errors out on `rsmm apply`,
    because `set_value_after_label` anchors on the expected old value.
    """
    notes: list[str] = []
    lines = [
        "[[content]]",
        'kind          = "item"',
        f'id            = "{mod_id}_item_1"',
    ]
    found = None
    if base:
        from rsmm.cli import cmd_items
        found = cmd_items._find_item(base)
        if found is None:
            notes.append(f"base {base!r} is not a known vanilla item — left as "
                         "a placeholder. `rsmm items list` shows the real ids.")
    if found is None:
        lines += [
            f'base          = {_toml_str(base or _KIND_BASE_HINT["item"])}',
            f'name          = {_toml_str(name or mod_id)}',
            f'description   = {_toml_str(desc or "")}',
        ]
        # An explicit --rarity is the author's answer, not something mined:
        # dropping it because the base could not be read (no game install on
        # this machine, an unknown id) silently loses what they typed. With
        # no base to read and no flag, there is nothing to infer, so the key
        # is left out rather than guessed.
        if rarity:
            lines.append(f'rarity        = {_toml_str(rarity)}')
        lines += [
            f'icon          = {_toml_str(icon or "GreenArmor")}'
            "          # vanilla icon id, or assets/<file>.png",
            "# value_patches = [[\"<label>\", <old>, <new>]]  "
            "# `rsmm items show <base>` lists label + default",
        ]
        return lines, notes, None

    from rsmm.engine import magic_item_cook as cook
    from rsmm.engine.talent_values import list_talent_values
    base_id, base_rarity, path = found
    data = path.read_bytes()
    base_icon = cook.find_icon(data) or "GreenArmor"
    # A shadowed label's inline value is overridden by a selector, so patching
    # it is a silent no-op — `set_value_after_label` refuses it outright. Never
    # seed one into a scaffold that is meant to apply cleanly.
    shadowed = {tv.label for tv in list_talent_values(data) if tv.is_overridden}
    # `list_value_fields` is best-effort: it can report a (label, default)
    # pair whose default `set_value_after_label` then can't re-find, which
    # would ship a scaffold that fails its own lint. Seed only what actually
    # round-trips — the same call the applier will make.
    fields = []
    unpatchable = 0
    for lb, val in cook.list_value_fields(data):
        if lb in shadowed:
            continue
        try:
            cook.set_value_after_label(data, lb, val, val)
        except (ValueError, TypeError):
            unpatchable += 1
            continue
        fields.append((lb, val))
    lines += [
        f'base          = {_toml_str(f"{base_rarity}/{base_id}")}',
        f'name          = {_toml_str(name or mod_id)}',
        f'description   = {_toml_str(desc or "")}',
        f'rarity        = {_toml_str(rarity or base_rarity)}',
        f'icon          = {_toml_str(icon or base_icon)}',
    ]
    if fields:
        patches = ", ".join(f"[{_toml_str(lb)}, {val!r}, {val!r}]"
                            for lb, val in fields)
        lines += [
            "# [label, current, new] — currents are read from the base, so",
            "# these apply as-is. Change the third number to retune.",
            f"value_patches = [{patches}]",
        ]
        notes.append(f"seeded {len(fields)} value field(s) from {base_id}: "
                     + ", ".join(lb for lb, _ in fields))
    else:
        lines.append("# value_patches = []   # this base exposes no editable "
                     "f32 value fields")
        notes.append(f"{base_id} exposes no editable value fields — the clone "
                     "will differ by name/description/icon only.")
    if shadowed:
        notes.append(f"skipped {len(shadowed)} shadowed label(s) "
                     f"({', '.join(sorted(shadowed))}) — their value is "
                     "overridden by a selector, so patching them is a no-op.")
    if unpatchable:
        notes.append(f"skipped {unpatchable} label(s) whose default didn't "
                     "round-trip — `rsmm items show` lists them, but they "
                     "aren't safely patchable by label.")
    return lines, notes, f"{base_rarity}/{base_id}"


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    kind: str | None = None
    opts: dict[str, str | None] = {
        "kind": None, "base": None, "name": None,
        "desc": None, "icon": None, "rarity": None,
    }
    args: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(_USAGE)
            return 0
        matched = False
        for opt in opts:
            if a == f"--{opt}":
                i += 1
                if i >= len(argv):
                    print(f"--{opt} takes a value", file=sys.stderr)
                    return 2
                opts[opt] = argv[i]
                matched = True
                break
            if a.startswith(f"--{opt}="):
                opts[opt] = a.split("=", 1)[1]
                matched = True
                break
        if not matched:
            if a.startswith("-"):
                print(f"unknown option: {a}\n\n{_USAGE}", file=sys.stderr)
                return 2
            args.append(a)
        i += 1
    kind = opts["kind"]
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

    # Pick the donor before anything is written, so backing out of the picker
    # leaves no half-scaffolded directory behind.
    if kind == "item" and not opts["base"] and _interactive():
        opts["base"] = _pick_base()

    (target / "assets").mkdir(parents=True)

    # Non-confirmed kinds must opt into [mod] experimental = true (the lint
    # confidence gate rejects them otherwise) and ship disabled by default so
    # a scaffolded experimental/guess mod doesn't auto-apply unverified bytes.
    conf = kind_confidence(kind) if kind else "confirmed"
    experimental = conf != "confirmed"

    notes: list[str] = []
    manifest = [
        "[mod]",
        f'id          = "{mod_id}"',
        f'name        = {_toml_str(opts["name"] or mod_id)}',
        'version     = "0.1.0"',
        'author      = "you"           # <- your name; `rsmm lint` flags this default',
        f'description = {_toml_str(opts["desc"] or "")}',
        f"enabled     = {'false' if experimental else 'true'}",
        'sdk_version = ">=3.0,<4"',
        # Scaffold what the store card renders, rather than leaving an author
        # to discover the fields exist only when their published mod shows up
        # blank. Empty values are what `rsmm lint` warns on, so the prompt to
        # fill them in is the scaffold itself.
        'tags        = []              # e.g. ["items", "balance"] — how players find it',
        'license     = ""              # e.g. "MIT" — omit and nobody may fork it',
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
    elif kind == "item":
        # The item block is mined from the chosen base rather than templated,
        # so the scaffold applies without hand-editing every field.
        item_lines, notes, resolved_base = _item_content_lines(
            mod_id, opts["base"], opts["name"], opts["desc"],
            opts["icon"], opts["rarity"])
        manifest += ["", f"# kind {kind!r} confidence: {conf}", *item_lines]
    elif kind in _FOLDER_SEED:
        # Folder form: the content lives in its own directory and is discovered,
        # so the manifest gains nothing but a pointer comment.
        from rsmm.sdk.discovery import KIND_DIRS

        dirname = next(d for d, k in KIND_DIRS.items() if k == kind)
        slug = f"{mod_id}_{kind}_1".replace("-", "_")
        folder = target / dirname / slug
        folder.mkdir(parents=True, exist_ok=True)
        seed = [f"# {kind} — confidence: {conf}", *_FOLDER_SEED[kind]]
        # An explicitly passed --base must always land as a real key. A hint is
        # only a placeholder, so it stays commented; conflating the two is how
        # `--base` got silently dropped for every folder kind.
        if opts["base"]:
            seed.append(f'base = {_toml_str(opts["base"])}')
        elif kind != "poi" and (hint := _KIND_BASE_HINT.get(kind)):
            seed.append(f'# base = {_toml_str(hint)}   # vanilla id to clone')
        (folder / f"{kind}.toml").write_text("\n".join(seed) + "\n",
                                             encoding="utf-8")
        manifest += [
            "",
            f"# Content lives in {dirname}/ — one folder per {kind}, discovered",
            f"# automatically. Edit {dirname}/{slug}/{kind}.toml, or add another",
            "# folder beside it. Nothing to declare here.",
        ]
    elif kind:
        base = opts["base"] or _KIND_BASE_HINT.get(kind, "<vanilla id to clone>")
        manifest += [
            "",
            f"# kind {kind!r} confidence: {conf}",
            "[[content]]",
            f'kind          = "{kind}"',
            f'id            = "{mod_id}_{kind}_1"',
            f'base          = {_toml_str(base)}',
            f'name          = {_toml_str(opts["name"] or f"{mod_id} sample {kind}")}',
            f'description   = {_toml_str(opts["desc"] or "")}',
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
        f'name = "{opts["name"] or mod_id}"\n',
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {mod_id}\n\nDescribe your mod here.\n", encoding="utf-8",
    )
    print(f"Created {target}" + (f" (kind={kind}, confidence={conf})" if kind else ""))
    for note in notes:
        print(f"  · {note}")
    if experimental:
        print(f"  ! kind {kind!r} is {conf!r}: emitted bytes are NOT verified "
              "in-game. Scaffolded with experimental = true and enabled = "
              "false. Flip enabled once you've confirmed it loads.")
    if kind == "item" and resolved_base:
        print(f"Next: `rsmm items show {resolved_base}` to see every editable "
              f"field, then `rsmm lint {mod_id}` and `rsmm apply`.")
    else:
        print("Next: edit init.lua + manifest.toml, then `rsmm apply`.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
