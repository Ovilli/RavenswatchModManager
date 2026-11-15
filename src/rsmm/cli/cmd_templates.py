"""`rsmm templates` — every shipped button a hero written from scratch can lend.

    rsmm templates                       every hero's buttons, one line each
    rsmm templates Red                   Scarlet's buttons
    rsmm templates Red --button "Wolf Primary"
                                         one button: its clips and numbers (the
                                         knobs `clips` / `values` take)

A button names one as ``template = "<Hero>: <button>"`` in
``[content.frame.abilities.<slot>]`` (engine/ability_template.py).
"""

from __future__ import annotations

import argparse
import json
import sys


def _read(ref: str):
    from rsmm.engine import corpus
    return corpus.read("EntitySettings/" + ref.replace("\\", "/") + ".EntitySettingsResource.gen")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm templates", description=__doc__.split("\n\n")[0])
    ap.add_argument("hero", nargs="?", help="a hero's folder name: Red, Kintaro, Geppetto ...")
    ap.add_argument("--button", help="one button: its clips and numbers")
    ap.add_argument("--json", action="store_true", help="the catalog as JSON")
    args = ap.parse_args(argv)

    from rsmm.engine import ability_template as AT
    try:
        entries = AT.catalog(_read, [args.hero.removeprefix("Hero_")] if args.hero else None)
    except AT.TemplateError as e:
        print(e, file=sys.stderr)
        return 1
    if args.button:
        entries = [e for e in entries if args.button in e.names]
        if not entries:
            print(f"no button {args.button!r} (rsmm templates {args.hero or ''} lists them)",
                  file=sys.stderr)
            return 1
    if not entries:
        print("no hero buttons found (no game install or mirror?)", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([e.__dict__ for e in entries], indent=1))
        return 0
    for e in entries:
        alias = f"  (also: {', '.join(n for n in e.names if n != e.button)})" \
            if len(e.names) > 1 else ""
        print(f'template = "{e.hero}: {e.button}"{alias}')
        if not args.button:
            continue
        print(f"  starts: {e.entry}")
        print("  clips (clips = { \"<clip>\" = \"<new clip>\" }):")
        for c in e.clips:
            print(f"    {c.rsplit(chr(92), 1)[-1]}    {c}")
        print("  numbers (values = { \"<part>\" = <number> }):")
        for k, v in sorted(e.values.items()):
            print(f"    {k} = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
