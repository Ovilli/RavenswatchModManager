#!/usr/bin/env python3
"""`rsmm safe-mode` — drive the SDK health quarantine.

Subcommands:
  safe-mode            : show current quarantine + canary
  safe-mode --reset <id>: clear the crash counter for one mod
  safe-mode --clear    : clear every quarantine + delete the canary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.cli.apply_mods import find_game_dir
from rsmm.engine.paths import COOKING_SUBDIR
from rsmm.sdk.health import Health


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm safe-mode")
    ap.add_argument("--game-dir", type=Path, default=None)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--reset", metavar="MODID",
                   help="clear the crash counter for one mod")
    g.add_argument("--clear", action="store_true",
                   help="clear every quarantine + delete the boot canary")
    g.add_argument("--bisect", action="store_true",
                   help="record a bisect step: disable half the remaining "
                        "non-quarantined mods so the next launch narrows "
                        "the search. Re-run after each launch.")
    args = ap.parse_args(argv)

    game = args.game_dir or find_game_dir()
    if not game:
        print("Could not autodetect Ravenswatch install. "
              "Pass --game-dir.", file=sys.stderr)
        return 1
    cooking = game / COOKING_SUBDIR
    if not cooking.is_dir():
        print(f"_Cooking not found at {cooking}", file=sys.stderr)
        return 1
    h = Health(cooking)

    if args.reset:
        h.re_enable(args.reset)
        print(f"reset {args.reset}")
        return 0
    if args.clear:
        st = h.load()
        for mid in list(st.mods):
            h.re_enable(mid)
        h.clear_canary()
        print("cleared quarantine + canary")
        return 0
    if args.bisect:
        return _bisect_step(h)

    # show state
    st = h.load()
    if not st.mods:
        print("no health entries")
    else:
        print(f"threshold = {st.threshold}")
        for mid, body in sorted(st.mods.items()):
            tag = "DISABLED" if body.disabled_by_health else "ok"
            print(f"  [{tag:>8}] {mid:24}  crashes={body.crashes}  "
                  f"last_error={body.last_error[:60]!r}")
    canary = h.read_canary()
    if canary:
        print(f"\nstale boot canary present: last_step={canary.get('last_step')!r}")
        attrib = h.attribute_crash(canary)
        if attrib:
            print(f"  attributed to: {attrib}")
    else:
        print("\nno boot canary (last shutdown was clean)")
    return 0


def _bisect_step(h: Health) -> int:
    """Advance one bisect step.

    Heuristic: among enabled, non-quarantined mods, mark the bottom half
    (sorted by id) as quarantined. After the user re-launches:
      * crashed again -> remaining half contains the culprit; re-run
        to narrow further.
      * loaded clean  -> culprit is in the disabled half; call
        `rsmm safe-mode --reset <id>` on suspects.
    Idempotent across runs because each step bumps `crashes` to
    threshold for the suspects, which the applier reads.
    """
    import tomllib
    from rsmm.engine.paths import MODS_DIR
    st = h.load()
    quarantined = {mid for mid, m in st.mods.items() if m.disabled_by_health}
    candidates: list[str] = []
    if MODS_DIR.is_dir():
        for entry in sorted(MODS_DIR.iterdir()):
            if not entry.is_dir() or entry.name.startswith(("_", ".")):
                continue
            mf = entry / "manifest.toml"
            if not mf.exists():
                continue
            try:
                tbl = tomllib.loads(mf.read_text(encoding="utf-8"))
                meta = tbl.get("mod", {})
                mid = str(meta.get("id", entry.name))
                if not bool(meta.get("enabled", True)):
                    continue
                if mid in quarantined:
                    continue
                candidates.append(mid)
            except Exception:
                continue
    if not candidates:
        print("nothing to bisect — no enabled, non-quarantined mods left")
        return 0
    half = max(1, len(candidates) // 2)
    suspects = candidates[:half]
    for mid in suspects:
        h.record_crash(mid, "safe-mode --bisect")
        # Force the threshold for the suspect so the applier disables it
        # immediately, regardless of prior crash count.
        st2 = h.load()
        sm = st2.mods.get(mid)
        if sm and not sm.disabled_by_health:
            sm.disabled_by_health = True
            h.save(st2)
    print(f"bisect step: disabled {len(suspects)} of {len(candidates)} "
          f"candidates: {', '.join(suspects)}")
    print("now re-run the game; then `rsmm safe-mode --bisect` again to narrow.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
