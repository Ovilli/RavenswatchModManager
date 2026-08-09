#!/usr/bin/env python3
"""Write structured `locator` blocks for the symbols whose anchor is known.

Every entry here was derived while relocating that symbol by hand, so the
anchor is not a guess — it is the thing that actually identified the function
in Ghidra. Recording it as data is what stops the next game patch from turning
this into another manual session: `tools/symbol_locate.resolve_locator` can
re-find the routine from these keys alone.

Run with --check to assert every locator still resolves to the address the map
records. That check is the point: a locator that silently stops matching is a
locator that would have failed you after the patch, and you find out now.

    tools/backfill_locators.py            # report
    tools/backfill_locators.py --apply    # write into data/symbols.json
    tools/backfill_locators.py --check    # verify locators resolve (CI-able)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from symbol_locate import Build, resolve_locator  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SYM = REPO / "data" / "symbols.json"
CORPUS = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
VFTABLES = REPO / "docs" / "_re" / "out_new" / "vftables.jsonl"

# name -> locator. Keys are intersected, so give the most decisive one you have
# and add corroboration only where it is genuinely independent.
LOCATORS: dict[str, dict] = {
    # --- vftable slots: an identity, not a heuristic -----------------------
    "EnemyDef_PostLoad": {
        "vftable": {"class": "oCDtEnemyDefinition", "slot": 18},
        "calls": ["Registry_RegisterInstance", "ResourceRef_Resolve"],
        "offsets": ["0x2e8", "0x318", "0x2b8", "0x2c0", "0x2c8", "0x2cc", "0x2d0"],
    },
    "EnemyTribeDef_PostLoad": {
        "vftable": {"class": "oCDtEnemyTribeDefinition", "slot": 18},
        "calls": ["Registry_RegisterInstance", "ResourceRef_Resolve"],
        "offsets": ["0x2a0", "0x2a8"],
    },
    "BookController_ResolveTabs": {
        "vftable": {"class": "oCDtEntityCpnt3DBookController", "slot": 28},
        "offsets": ["0xf8", "0x120"],
    },

    # --- call graph -------------------------------------------------------
    "Registry_RegisterInstance": {
        "called_by": ["EnemyDef_PostLoad", "EnemyTribeDef_PostLoad"],
        "calls": ["Registry_EnumInstances"],
        "offsets": ["0x280"],
        "lines_max": 40,
    },
    "Registry_EnumInstances": {
        "called_by": ["Registry_RegisterInstance"],
        "consts": ["0xde5fb9d2630458e9"],
    },
    "ResourceRef_Resolve": {
        "called_by": ["EnemyDef_PostLoad", "EnemyTribeDef_PostLoad"],
        "offsets": ["0x28", "0x30", "0x38"],
    },
    "Netcode_DropPeer": {
        "called_by": ["Netcode_PeerStateTick"],
        "offsets": ["0x60"],
    },
    "MagicalObject_SpawnAllObjects": {
        "called_by": ["InitialLoading_LoadAllDefinitions"],
        "strings": ["oCEntitySpawnData::vftable"],
        "lines_min": 100, "lines_max": 170,
    },
    "HeroDef_LoadBaseEntity": {
        "called_by": ["LevelLoad_Orchestrator"],
        "offsets": ["0x8a0", "0x8b0", "0x8c0", "0x8c8", "0x8d0"],
        "lines_max": 200,
    },
    # The skin-spec offsets do not appear literally: Ghidra scales pointer
    # arithmetic by pointee size, so herodef+0x900 renders as `param_1 + 0x120`
    # on a longlong*. Anchor on the call site and size instead.
    "HeroDef_LoadSkinEntity": {
        "called_by": ["LevelLoad_Orchestrator"],
        "offsets": ["0x120"],   # the SCALED form of herodef+0x900
        "lines_min": 130, "lines_max": 155,
    },
    "MapCtx_DistributeEnemyCampTiers": {
        "called_by": ["LevelLoad_Orchestrator"],
        "calls": ["Property_EvaluateByGuid"],
        "offsets": ["0xc8", "0xd0", "0x288", "0x28c", "0x290", "0x298"],
    },
    "MapCtx_LinkPairedSpawners": {
        "called_by": ["LevelLoad_Orchestrator"],
        "offsets": ["0x198", "0x1a0", "0x110", "0xf8", "0x570"],
    },
    "EventQueue_Drain": {
        "called_by": ["LevelLoad_Orchestrator"],
        "offsets": ["0x30", "0x38", "0x48"],
    },
    "EnemyCamp_TribeEntryBuilder": {
        "called_by": ["EnemyCamp_TierSelector"],
        "strings": ["SearchFilter"],
        "offsets": ["0x720", "0x2c0"],
    },
    "Property_EvaluateByGuid": {
        "called_by": ["MapCtx_DistributeEnemyCampTiers"],
        "lines_min": 100, "lines_max": 140,
    },
    "Netcode_Channel_LookupById": {
        "called_by": ["NamedEvent_HeroUnsubscribeAll"],
        "consts": ["0xde5fb9d2630458e9"],
        "lines_min": 140, "lines_max": 180,
    },
    # One lookup+unsubscribe pair per hero event. 146 functions call
    # Channel_Unsubscribe; this is the only one that calls it thirty-odd times.
    "NamedEvent_HeroUnsubscribeAll": {
        "calls_at_least": {"Netcode_Channel_Unsubscribe": 20},
    },
    # A leaf with no strings and no notable constants. What identifies it is
    # the company it keeps: every static-init event-name interner calls
    # Crc32_TableInit and then this, so the two share their 1658 callers
    # exactly, and only 10 functions in the corpus are called that often.
    "NamedEvent_Id_FromCrc": {
        "co_called_with": ["Crc32_TableInit"],
        "callers_min": 1500,
        "lines_min": 20, "lines_max": 40,
    },

    # --- log strings the routine itself carries ---------------------------
    "Netcode_PeerStateTick": {
        "strings": ["EP2PConnectionState::eInterrupted -> disconnect"],
    },
    "EnemyCamp_TierSelector": {
        "strings": ["Generation complete !"],
    },
    "LevelLoad_Orchestrator": {
        "strings": ["Level load - MapSceneContext OnLevelStart",
                    "Level load - Rebuild navmesh"],
    },
    "Reward_InitAllRewards": {
        "strings": ["Seed : {0} ; Base seed {1}",
                    "Fill remaining slots with random rewards"],
    },
    "InitialLoading_LoadAllDefinitions": {
        "strings": ["InitialLoading - Load all definitions",
                    "InitialLoading - MagicalObject SpawnAllObjects"],
    },
    "Definitions_LoadGroup": {
        "strings": ["Definitions"],
        "called_by": ["InitialLoading_LoadAllDefinitions"],
    },

    # --- class identity ---------------------------------------------------
    "EnemyDefinition_ctor": {
        "strings": ["oCDtEnemyDefinition::vftable"],
        "offsets": ["0x2c0", "0x2dc", "0x2e0"],
    },
    # The pair sits immediately before NamedEvent_Dispatch in the CustomFlag
    # neighbourhood; both are 2-arg 0x18-stride string-set tests. ContainsAll
    # is the one with the |A| >= |B| precondition, so it is the SHORTER of the
    # two — the size bound is what separates them.
    # An adjacent pair of 2-arg 0x18-stride string-set tests sharing the memcmp
    # temp `_Buf2`. Nothing in either body distinguishes them semantically to a
    # text match — ContainsAll differs only by its leading |A| >= |B| early-out,
    # which costs it a few lines. So size is the discriminator, and the bounds
    # are tight deliberately: if a rebuild moves them the locator FAILS rather
    # than quietly returning the sibling, which is the wrong answer that
    # matters here.
    "CustomFlagList_ContainsAll": {
        "strings": ["_Buf2"],
        "offsets": ["0x8", "0x10", "0x18"],
        "lines_min": 75, "lines_max": 80,
    },
    "CustomFlagList_ContainsAny": {
        "strings": ["_Buf2"],
        "offsets": ["0x8", "0x10", "0x18"],
        "lines_min": 68, "lines_max": 73,
    },
    "MagicalObject_RegisterInstance": {
        "offsets": ["0xd70", "0xd78", "0xd7c", "0xd80", "0xd88", "0xf0",
                    "0x1b0", "0x1b8"],
        "lines_min": 120, "lines_max": 200,
    },
    # --- skins ------------------------------------------------------------
    "Entry_Ctor": {
        "strings": ["oCAdditionalContent::vftable"],
        "lines_min": 35, "lines_max": 55,
    },
    "SkinRoster_Build": {
        "calls": ["Entry_Ctor"],
    },
    "String_Assign": {
        "called_by": ["SkinRoster_Build"],
        "callers_min": 2000,
        "lines_max": 60,
    },
    "SkinGrid_Populate": {
        "calls": ["Vector_Grow"],
        "offsets": ["0x2f8", "0x300", "0x304"],
        "lines_min": 300, "lines_max": 450,
    },

    "GameScene_FindContextByTester": {
        "offsets": ["0x58", "0x60", "0x68", "0x70"],
        "called_by": ["MapCtx_DistributeEnemyCampTiers"],
    },
    # The resize itself, not the insert helper that wraps it. Both allocate, so
    # the allocator call does not separate them — being one of the ten most
    # called functions in the binary does. Same routine as PtrVector_Resize.
    "Vector_Grow": {
        "strings": ["_realloc_base", "_malloc_base"],
        "callers_min": 2000,
        "offsets": ["0xc"],
        "lines_min": 30, "lines_max": 45,
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    doc = json.loads(SYM.read_text())
    by_name = {s["name"]: s for s in doc["symbols"]}
    build = Build(CORPUS, VFTABLES)

    located = {
        s["name"]: int(str(s["raw"]).split("_", 1)[1], 16)
        for s in doc["symbols"]
        if str(s.get("raw") or "").startswith("FUN_")
    }

    exact = ambiguous = wrong = unresolved = 0
    for name, loc in sorted(LOCATORS.items()):
        sym = by_name.get(name)
        if sym is None:
            print(f"  ?        {name}: not in the symbol map")
            continue
        truth = located.get(name)
        hits, why = resolve_locator(build, loc, located)

        if not hits:
            unresolved += 1
            print(f"  UNRESOLVED {name}: {why}")
        elif hits == [truth]:
            exact += 1
        elif truth in hits:
            ambiguous += 1
            print(f"  AMBIGUOUS  {name}: {len(hits)} hits (truth included) via {why}")
        else:
            wrong += 1
            print(f"  WRONG      {name}: {[hex(h) for h in hits[:4]]} "
                  f"!= 0x{truth:x} via {why}")

        if args.apply:
            sym["locator"] = loc

    total = exact + ambiguous + wrong + unresolved
    print(f"\n{total} locators")
    print(f"  resolve EXACTLY to the mapped address : {exact:3} ({exact / total:.0%})")
    print(f"  ambiguous (truth in the shortlist)    : {ambiguous:3}")
    print(f"  resolve to the WRONG function         : {wrong:3}")
    print(f"  do not resolve at all                 : {unresolved:3}")

    if args.apply:
        SYM.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"wrote {len(LOCATORS)} locator(s) to {SYM}")
    if args.check and (wrong or unresolved):
        print("\nFAIL: a locator that does not resolve today would not have "
              "survived the next game patch either.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
