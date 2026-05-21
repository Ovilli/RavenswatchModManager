#!/usr/bin/env python3
"""Mine unlock-condition vftable slots into mods/MerlinUnlock/pointers.json.

Reads `data/vftables.jsonl` (produced by
`scripts/ghidra_scripts/ExportVftables.java`) and writes the slot-3 entry
of every oIGameUnlockConditionSettings-family vftable. Slot 3 is the
`IsUnlocked` virtual; slot 0 is `GetClassId`, slot 2 is the destructor,
slots 4-7 are CRT thunks (confirmed against decompiled bodies).

Run after the Ghidra decompile + vftable export passes:

    python3 scripts/ghidra_export.py     # ~30-90 min, once per build
    /path/to/analyzeHeadless ghidra_project Ravenswatch \\
        -scriptPath scripts/ghidra_scripts \\
        -process Ravenswatch.exe -noanalysis -readOnly \\
        -postScript ExportVftables.java data/vftables.jsonl
    python3 scripts/mine_merlin_unlock.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_JSONL = REPO / "data" / "vftables.jsonl"
DEFAULT_OUT   = REPO / "mods" / "MerlinUnlock" / "pointers.json"

# Slot 3 = IsUnlocked / Evaluate, verified by decompile.
ISUNLOCKED_SLOT = 3

# Which vftables we care about. Maps sym substring -> pointers.json key.
WANTED: dict[str, str] = {
    "oIGameUnlockConditionSettings::vftable":
        "oIGameUnlockConditionSettings_IsUnlocked",
    "HeroProgressionUnlockConditionSettings::vftable":
        "HeroProgressionUnlockConditionSettings_IsUnlocked",
    "HeroRankGameLockConditionSettings::vftable":
        "HeroRankGameLockConditionSettings_IsUnlocked",
    "AdditionalContentGameUnlockConditionSettings::vftable":
        "AdditionalContentGameUnlockConditionSettings_IsUnlocked",
    "NamedEventGameLockConditionSettings::vftable":
        "NamedEventGameLockConditionSettings_IsUnlocked",
    "oCGameLockSettings::vftable":
        "oCGameLockSettings_Evaluate",
}


def mine(jsonl: Path) -> dict[str, str]:
    hooks: dict[str, str] = {}
    with jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = str(rec.get("sym", ""))
            for needle, key in WANTED.items():
                if needle in sym and key not in hooks:
                    slots = rec.get("slots") or []
                    for s in slots:
                        if s.get("i") == ISUNLOCKED_SLOT:
                            hooks[key] = "FUN_" + str(s.get("va")).lstrip("0x")
                            break
    return hooks


def fingerprint(exe: Path | None) -> str | None:
    if exe is None or not exe.is_file():
        return None
    import hashlib
    h = hashlib.sha256()
    with exe.open("rb") as f:
        h.update(f.read(4096))
    return h.hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in",  dest="jsonl", default=str(DEFAULT_JSONL))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--exe", default=None,
                    help="optional path to Ravenswatch.exe for build fingerprint")
    args = ap.parse_args()

    jsonl = Path(args.jsonl)
    if not jsonl.is_file():
        print(
            f"vftable dump not found: {jsonl}\n"
            f"Run the Ghidra ExportVftables.java pass first.",
            file=sys.stderr,
        )
        return 1

    hooks = mine(jsonl)
    missing = [k for k in WANTED.values() if k not in hooks]
    if missing:
        print(
            "warning: missing vftables:\n  " + "\n  ".join(missing) +
            "\nGhidra may not have recovered every RTTI symbol. Inspect:\n"
            f"  jq -r '.sym' {jsonl} | grep UnlockCondition",
            file=sys.stderr,
        )

    out = {
        "_comment_": (
            "Slot 3 of each *UnlockConditionSettings vftable is IsUnlocked "
            "(verified by decompile). Values are Ghidra function names "
            "resolved at runtime via the pattern DB so they work "
            "regardless of ASLR. Only three are actually used by "
            "init.lua (AdditionalContent, NamedEvent, HeroProgression); "
            "the rest are mined for reference."
        ),
        "hook_sig": "ipp",
        "hooks": hooks,
    }
    fp = fingerprint(Path(args.exe)) if args.exe else None
    if fp:
        out["build_fingerprint"] = fp

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    for k, v in hooks.items():
        print(f"  {k} = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
