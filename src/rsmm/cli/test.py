"""
rsmm test — diff a mod's patch plan against a checked-in fixture.

Usage:
    rsmm test                  # run every mod that has a fixture
    rsmm test <mod-id>         # only this mod
    rsmm test <mod-id> --record  # write the current plan as expected

For each mod that has `mods/<id>/build.py` we execute it in dry-run
mode (SDK records calls without writing files), capture
`Mod.plan()`, and compare to `mods/<id>/tests/expected_plan.json`.
A mismatch means either the mod author changed something (rerun
with --record) or the SDK / asset map drifted under them
(investigate before recording).

Why this matters: as the rsmm SDK gains new verbs, existing mods
should keep producing identical output. Fixture diffs catch a
regression instantly.
"""

from __future__ import annotations
import argparse
import json
import runpy
import sys
from pathlib import Path

from rsmm.engine.paths import MODS_DIR


def _load_plan(build_py: Path) -> list[dict]:
    """Execute build.py with SDK in dry-run mode and grab the plan
    of whichever Mod context was used. Mods conventionally use
    a single `with sdk.Mod(...) as m:` block — we hook into Mod to
    capture its plan() output at __exit__."""
    from rsmm import sdk

    captured: list[list[dict]] = []
    orig_exit = sdk.Mod.__exit__

    def patched_exit(self, exc_type, exc, tb):  # noqa: ANN001
        captured.append(self.plan())
        self.dry_run = True   # avoid writing manifest in test mode
        return orig_exit(self, exc_type, exc, tb)

    sdk.Mod.__exit__ = patched_exit          # type: ignore[method-assign]
    try:
        runpy.run_path(str(build_py), run_name="__main__")
    finally:
        sdk.Mod.__exit__ = orig_exit         # type: ignore[method-assign]

    if not captured:
        raise RuntimeError(f"{build_py}: no sdk.Mod() context found")
    # Flatten: most mods produce one plan, some produce many.
    out: list[dict] = []
    for p in captured:
        out.extend(p)
    return out


def _fixture_path(mod_dir: Path) -> Path:
    return mod_dir / "tests" / "expected_plan.json"


def _test_one(mod_dir: Path, record: bool, log) -> bool:
    name = mod_dir.name
    build = mod_dir / "build.py"
    if not build.is_file():
        log(f"SKIP {name}: no build.py")
        return True
    try:
        plan = _load_plan(build)
    except Exception as e:
        log(f"FAIL {name}: build.py raised {type(e).__name__}: {e}")
        return False
    fix = _fixture_path(mod_dir)
    if record:
        fix.parent.mkdir(parents=True, exist_ok=True)
        fix.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        log(f"REC  {name}: wrote {fix.relative_to(MODS_DIR.parent)} "
            f"({len(plan)} patches)")
        return True
    if not fix.is_file():
        log(f"WARN {name}: no fixture at {fix.relative_to(MODS_DIR.parent)} "
            f"(run with --record to create)")
        return True
    expected = json.loads(fix.read_text())
    if expected == plan:
        log(f"OK   {name}: {len(plan)} patches match")
        return True
    log(f"FAIL {name}: plan differs from fixture")
    _print_diff(expected, plan, log)
    return False


def _print_diff(a: list[dict], b: list[dict], log) -> None:
    # Cheap line diff — full json.dumps comparison is enough to see
    # which patch changed for a modder; we don't need a structural
    # diff library.
    al = json.dumps(a, indent=2, sort_keys=True).splitlines()
    bl = json.dumps(b, indent=2, sort_keys=True).splitlines()
    import difflib
    for line in difflib.unified_diff(al, bl, lineterm="",
                                     fromfile="expected", tofile="actual"):
        log("  " + line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mod_id", nargs="?",
                    help="only test this mod (otherwise: every mod)")
    ap.add_argument("--record", action="store_true",
                    help="write the current plan as the new fixture")
    args = ap.parse_args()

    def log(s: str) -> None:
        print(s, flush=True)

    if args.mod_id:
        targets = [MODS_DIR / args.mod_id]
        if not targets[0].is_dir():
            log(f"no such mod: {targets[0]}")
            return 2
    else:
        targets = sorted(p for p in MODS_DIR.iterdir()
                         if p.is_dir() and not p.name.startswith("_"))

    fails = 0
    for t in targets:
        if not _test_one(t, args.record, log):
            fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
