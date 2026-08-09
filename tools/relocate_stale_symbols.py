#!/usr/bin/env python3
"""Relocate `unverified` symbols whose `raw` address is from an older build.

Why this exists
---------------
44 of the 48 `status:"unverified"` symbols in data/symbols.json carry a `raw`
of the form ``FUN_<addr>`` that is NOT a function start in the shipped exe: the
.pdata table says every one of them lands *inside* some other function. They
are addresses from a build one or two patches old. The analysis behind them was
never lost — each symbol's `note` records the strings, class hashes and struct
offsets that identify the routine — but the pointer rotted, so the loader fails
closed and the capability is unavailable. Git shows this being re-done by hand
three times; this is the mechanical version.

Anchors, strongest first
------------------------
``vftable`` the note says "<Class> vftable+0xNN" / "vftable slot N". Resolved
            exactly against docs/_re/out_new/vftables.jsonl (RTTI-derived, same
            build as the corpus) — this is an identity, not a heuristic.
``callee``  the note names another symbol that is already `status:"ok"`, so its
            CURRENT address is known; the candidate must call it.
``string``  a quoted literal from the note, matched against the decompile text.
            Log/format strings survive patches verbatim and are near-unique.
``hash``    a 32-bit class hash / UID (outside the code VA range).
``offset``  struct offsets from the note (``+0x2e8``). Individually worthless —
            thousands of functions touch ``+0x10`` — but the notes list them in
            groups of 4-8, and a function containing the whole group is
            effectively unique. Scored as a FRACTION of the group, so a big
            function cannot win by accidentally containing two of them.

A candidate is only rewritten when it wins on a strong anchor AND beats the
runner-up by a clear margin AND is not already claimed by another symbol.
Corpus membership guarantees the address is a real function start, so an
applied address can never be mid-instruction (the false-ok failure mode that
produced this mess).

    tools/relocate_stale_symbols.py              # report
    tools/relocate_stale_symbols.py --apply      # rewrite unambiguous winners
    tools/relocate_stale_symbols.py --json

After --apply:
    rsmm symbols gen && python scripts/verify_symbol_resolve.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYM = REPO / "data" / "symbols.json"
CORPUS = REPO / "docs" / "_re" / "out_new" / "decompiled_new.jsonl"
VFTABLES = REPO / "docs" / "_re" / "out_new" / "vftables.jsonl"

# Lazily built shared corpus index for locator resolution (see main()).
_BUILD = None

# A quoted literal shorter than this matches half the binary ("ot", "id", ...).
MIN_STRING_ANCHOR = 6
# Hex literals in this range are code/data VAs from the OLD build — useless as
# content anchors and actively misleading (they resolve to nothing today).
VA_LO, VA_HI = 0x140000000, 0x142000000

# --------------------------------------------------------------------------
# Hand-confirmed relocations.
#
# The scorer below is a SHORTLISTER. Everything here was then read in Ghidra
# against the note and is recorded with the evidence that settled it, because
# the automated pick was wrong often enough to matter: it handed
# Netcode_DropPeer the address of Netcode_PeerStateTick (the note quotes a log
# string that lives in the CALLER), and it handed three different symbols the
# level-load orchestrator because that one function contains every stage
# string. `--apply` writes these plus any unambiguous scorer winner.
CONFIRMED: dict[str, tuple[str, str]] = {
    "EnemyDef_PostLoad": ("FUN_14031a800",
        "oCDtEnemyDefinition::vftable[18] (+0x90). Body matches the note "
        "exactly: tribe ref @+0x2e8 with class-desc default @+0x308 resolved "
        "into +0x318, push_back into tribe+0x2b8/+0x2c0, min/max folds into "
        "+0x2c8/+0x2cc/+0x2d0, then Registry_RegisterInstance."),
    "EnemyTribeDef_PostLoad": ("FUN_14031bae0",
        "oCDtEnemyTribeDefinition::vftable[18] (+0x90). Walks the 0x38-stride "
        "entry vector at +0x2a0/+0x2a8 through ResourceRef_Resolve, then "
        "Registry_RegisterInstance; never touches the runtime roster +0x2b8 — "
        "the distinguishing negative in the note."),
    "Registry_RegisterInstance": ("FUN_1403119d0",
        "Called by both PostLoad routines above. Per-instance registration "
        "counter at param_1[0x50] = +0x280 as documented; pushes into the "
        "global instance list and the per-class registry entry."),
    "Registry_EnumInstances": ("FUN_140241750",
        "Called by Registry_RegisterInstance to get the per-class entry. "
        "SwissTable find-or-insert keyed on *classDescPtr; writes out3 = "
        "{ctrl, entry, inserted u8} and inits the entry as {key, data=0, "
        "count=0} — the {key @+0, instance_data @+8, count @+0x10} layout."),
    "ResourceRef_Resolve": ("FUN_140492540",
        "Called by both PostLoad routines. Resolved flag read at +0x28 and "
        "resolved pointer written through param_3, per the 0x38-byte ref "
        "block in the note; looks up service id 0x53b64d."),
    "Vector_Grow": ("FUN_140155230",
        "new_cap is param_3 (R8) and param_2 (RDX) is unused — the note's "
        "exact ABI note. malloc/realloc of param_3*8, capacity stored at "
        "+0xc. Reached from both vector-insert helpers."),
    "Netcode_PeerStateTick": ("FUN_1402b03a0",
        "Iterates the peer array, reads the conn-state enum at peer+0xCC and "
        "skips 3; carries the EP2PConnectionState log strings including the "
        "eInterrupted disconnect branch. NOT DropPeer — the scorer picked this "
        "for DropPeer because the 'max reconnection time attempt' string the "
        "DropPeer note quotes is logged HERE, at the call site."),
    "Netcode_DropPeer": ("FUN_1402b4d50",
        "The call in PeerStateTick's 'max reconnection time attempt' branch. "
        "Swap-removes a peer from the same global array PeerStateTick walks "
        "(0x60 stride, count decremented)."),
    "HeroDef_LoadBaseEntity": ("FUN_14031ece0",
        "Called from the 'Level load - LoadAndGetRandomHeroEntity' stage, in "
        "the loop over the herodef list at gameScene+0x710 with count +0x718 "
        "— the exact pair recorded in the note."),
    "MapCtx_DistributeEnemyCampTiers": ("FUN_1401e8830",
        "First of the three calls under the 'MapSceneContext OnLevelStart' "
        "stage, i.e. before the reward roll (Reward_InitAllRewards) as the "
        "note says. Contains 7 of the note's 8 struct offsets (+0x288/+0x28c "
        "tier band, +0x290/+0x298 rows, weight +0x40); its neighbour has 1."),
    "MapCtx_LinkPairedSpawners": ("FUN_1401ebad0",
        "The call right AFTER the reward roll in the same stage. Contains all "
        "6 note offsets (+0x198/+0x1a0 spawner list, link +0x68, def +0x110 / "
        "+0xf8, register +0x570); the tier-distribute neighbour has 1."),
    "EnemyCamp_TierSelector": ("FUN_14032e790",
        "Carries the 'Generation complete !' and 'Min/Max power weight' log "
        "strings from the note; sole match in the corpus."),
    "EnemyCamp_TribeEntryBuilder": ("FUN_14032fe20",
        "Callee of the tier selector that references the map-def tribe list "
        "at mapdef+0x720 with 0x38 stride and the EnemyTribeDefInternal "
        "SearchFilter, and does NOT touch the tier-band offsets that identify "
        "the stage-3 filter."),
    "LevelLoad_Orchestrator": ("FUN_14028e5f0",
        "Holds all 15 'Level load - *' stage strings (hero entities, barks, "
        "'Enemies settings loading', map/tile defs, enemy camps, navmesh, "
        "sectorization) — the stage chain the note describes. This address "
        "was previously and wrongly assigned to HeroDef_LoadSkinEntity, which "
        "is one of the functions this orchestrator CALLS."),
    "Definitions_LoadGroup": ("FUN_140310300",
        "Sole corpus function whose only string literal is the 'Definitions' "
        "group name. Weaker than the rest of this table (no versiondef path "
        "reference survives in the body), so treat a failure here as the "
        "first suspect."),

    # --- second pass -------------------------------------------------------
    "MagicalObject_SpawnAllObjects": ("FUN_140259060",
        "Invoked from the boot orchestrator right after the 'InitialLoading - "
        "MagicalObject SpawnAllObjects' stage string as (DAT_14143cc18, "
        "scene) — DAT_14143cc18 IS g_MagicalObjectPool, so the call matches "
        "the declared void(void* pool, void* scene) exactly. Replaces the "
        "stale `anchor` (parent FUN_14025d9b0 + 0x70) that landed 2 bytes "
        "inside a call instruction; this is a real function start, so the "
        "hazard the note described is gone."),
    "NamedEvent_Id_FromCrc": ("FUN_14051f090",
        "uint(uint ns, uint crc) feeding bytes to the Crc32_TableInit table "
        "in exactly the documented interleave [ns.b0, crc.b0, ns.b1, crc.b1, "
        "...], init 0xffffffff, final invert. 1658 callers, all static-init "
        "event-name interners."),
    "Netcode_Channel_LookupById": ("FUN_140241a50",
        "param_3 is uint* (the interned u32 event id), mallocs exactly 0x20 "
        "and writes the id at +0x00 then zeroes +0x08/+0x10/+0x14/+0x18 — the "
        "channel-node layout in the note. Uses the same SwissTable probe "
        "constant. Called once per event by HeroUnsubscribeAll, paired 1:1 "
        "with Netcode_Channel_Unsubscribe."),
    "NamedEvent_HeroUnsubscribeAll": ("FUN_140395350",
        "Calls Netcode_Channel_Unsubscribe 34 times, each paired with a "
        "Netcode_Channel_LookupById — the 'one lookup+unsubscribe pair per "
        "event' shape the note calls the easiest place to read the hero "
        "event catalog. Single arg, like its HeroSubscribeAll twin."),
    "GameScene_FindContextByTester": ("FUN_14066cad0",
        "Two loops over (data @+0x58, count @+0x60) and (data @+0x68, count "
        "@+0x70), each calling tester vtbl+0x8 Test(ctx) and returning the "
        "first match — the note verbatim."),
    "EventQueue_Drain": ("FUN_1406642d0",
        "Called as FUN_1406642d0(ctx + 0x1c0) immediately after the "
        "NamedEvent_Dispatch on the world dispatcher (+0x340) in the 'Level "
        "load - Generate rewards' stage — the exact post-GENERATE_REWARDS "
        "drain the note describes. Takes a critical section."),
    "Property_EvaluateByGuid": ("FUN_1406ab910",
        "In MapCtx_DistributeEnemyCampTiers: guarded by `if (spawner+0x68 <= "
        "0.0)` (the lazy value evaluation) and its false return leads "
        "straight into the settings-asset-path log fallback — both halves of "
        "the note's description."),
    "MagicalObject_RegisterInstance": ("FUN_1403abb90",
        "Matches all 9 offsets in the note: hero-owned set +0xd70/+0xd78/"
        "+0xd7c, secondary collection +0xd80/+0xd88, def holder +0xf0 with "
        "identity at +0x28, rarity +0x1b0/+0x1b8. The one-arg neighbour "
        "matches 3."),
    "CustomFlagList_ContainsAll": ("FUN_14066ac70",
        "Opens with `if (count_A < count_B) return 0` — the ALL precondition "
        "— then the nested 0x18-stride memcmp over {name @+8} with data @+8 "
        "and count @+0x10."),
    "CustomFlagList_ContainsAny": ("FUN_14066ad90",
        "Same 0x18-stride scan as its immediate neighbour but with no count "
        "precondition and an early return on first match; an empty B falls "
        "straight out with 0, i.e. 'Empty B => false' as documented."),
    "EnemyDefinition_ctor": ("FUN_1401df270",
        "MSVC ctor chain oISerializable -> oIResource -> oCDtDefinition -> "
        "oCDtEnemyDefinition, returning param_1. Sets the flag list at "
        "+0x2c0 to oCCustomFlagList::vftable, minTier f32 @+0x2dc = "
        "0x3dcccccd, and the tier range @+0x2e0 to {0, 5} — the note's "
        "initialisers."),
    "HeroDef_LoadSkinEntity": ("FUN_14031ea40",
        "Called from the orchestrator's 'Level load - "
        "LoadAndGetPlayedHeroEntity' stage as (herodef, u16 skin index, "
        "&out) — the (herodef, skinIdx u16) pair in the note. Sits directly "
        "before its HeroDef_LoadBaseEntity sibling. This is the symbol that "
        "was previously pointing at the orchestrator itself."),
    "BookController_ResolveTabs": ("FUN_140308cd0",
        "oCDtEntityCpnt3DBookController::vftable[28]. Loops exactly 5 tab "
        "entities read from self+0xf8 and writes each one's component into "
        "self+0x120.., pulling them with Entity_FindComponentByType and the "
        "tab type-descriptor global — the note's wire-up."),
}

# status=ok symbols proven to point at the WRONG function. Left resolvable but
# demoted so the loader fails closed instead of detouring a stranger.
DEMOTE: dict[str, str] = {
    "InitialLoading_SpawnMagicalObjects":
        "REDUNDANT (found 2026-08-09): the function this symbol described as "
        "'the caller that invokes SpawnAllObjects(pool, ...)' is the boot "
        "orchestrator FUN_140260b80, which is already "
        "InitialLoading_LoadAllDefinitions — every 'InitialLoading - *' stage "
        "body is inlined there. The callee it names is now carried by "
        "MagicalObject_SpawnAllObjects (FUN_140259060). Nothing left for this "
        "symbol to point at; hook the callee instead.",
}

# Two names that resolved to ONE function. Not an error — both are referenced
# by loader code — but silent duplication is how a future remap moves one and
# not the other, so it is recorded in both notes.
ALIASES: dict[str, str] = {
    "Vector_Grow":
        "SAME FUNCTION as PtrVector_Resize (relocation 2026-08-09 landed both "
        "on the one routine, and the two notes describe identical behaviour: "
        "param_3 is the new capacity, malloc/realloc of param_3*8, capacity "
        "at +0xc). Keep them in step on any future remap, or merge.",
    "PtrVector_Resize":
        "SAME FUNCTION as Vector_Grow — see that symbol's note.",
    "Entity_FindComponentByType":
        "SAME FUNCTION as Entity_GetComponentByTester (both resolve to "
        "FUN_1406e3210). Pre-existing duplication, recorded here so a future "
        "remap moves both or merges them.",
    "Entity_GetComponentByTester":
        "SAME FUNCTION as Entity_FindComponentByType — see that symbol's note.",
}


_QUOTED = re.compile(rf"['\"]([^'\"\n]{{{MIN_STRING_ANCHOR},80}})['\"]")
_HEX = re.compile(r"0x([0-9a-fA-F]{4,16})")
_OFFSET = re.compile(r"\+0x([0-9a-fA-F]{2,4})\b")
_CLASS = re.compile(r"\b((?:oC|oI|oe::)[A-Za-z0-9_:<>]{4,})")
_VFT_SLOT = re.compile(r"vftable\s*\+\s*0x([0-9a-fA-F]+)|vftable slot (\d+)")
_CODE_CALL = re.compile(r"FUN_(1[0-9a-f]{8})\(")


# --------------------------------------------------------------------------
# corpus


def assert_corpus_matches_exe(exe: Path | None = None) -> str:
    """Refuse to relocate against a corpus from a DIFFERENT game build.

    Every locator here works by matching CONTENT — strings, constants, struct
    offsets, call graph — against the decompiled corpus. If the corpus came
    from another build, those matches are just as confident and completely
    wrong, and the result is a `status="ok"` symbol pointing at unrelated code:
    the false-ok class this whole toolchain exists to prevent. The corpus used
    to carry no build identity at all, so the only way to notice was the
    accident of checking address overlap by hand.

    Returns a human-readable summary. Raises SystemExit on a mismatch.
    """
    meta_path = CORPUS.parent / "corpus.meta.json"
    if not meta_path.exists():
        raise SystemExit(
            f"{meta_path} missing — the corpus carries no build identity, so "
            f"there is no way to tell whether it describes the shipped exe. "
            f"Regenerate the corpus and stamp it before relocating anything."
        )
    meta = json.loads(meta_path.read_text())

    if exe is None:
        sys.path.insert(0, str(REPO / "scripts"))
        import gen_function_patterns as gen  # noqa: E402, I001
        exe = Path(gen.DEFAULT_EXE)
    if not exe.exists():
        # No exe to compare against (CI, a fresh clone). Say so rather than
        # silently trusting the stamp.
        return f"corpus stamp {meta['game_exe_sha256'][:12]} (exe not present; unverified)"

    sha = hashlib.sha256(exe.read_bytes()).hexdigest()
    if sha != meta.get("game_exe_sha256"):
        raise SystemExit(
            f"CORPUS/EXE MISMATCH — refusing to relocate.\n"
            f"  corpus was built from {meta.get('game_exe_sha256', '?')[:16]}\n"
            f"  the exe on disk is    {sha[:16]}\n"
            f"The game was patched since this corpus was generated. Content "
            f"matches against it would be confident and wrong. Regenerate the "
            f"corpus first, then re-stamp corpus.meta.json."
        )
    return (f"corpus verified against the shipped exe "
            f"({meta['function_count']} functions, build {sha[:12]})")


class Corpus:
    def __init__(self) -> None:
        self.code: dict[int, str] = {}
        self.calls: dict[int, set[int]] = {}
        for line in CORPUS.open():
            rec = json.loads(line)
            addr = int(rec["addr"], 16)
            body = rec.get("code") or ""
            self.code[addr] = body
            self.calls[addr] = {int(x, 16) for x in _CODE_CALL.findall(body)}

    def vftables(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for line in VFTABLES.open():
            rec = json.loads(line)
            out.setdefault(rec["sym"].replace("::vftable", ""), []).append(rec)
        return out


# --------------------------------------------------------------------------
# anchors


def anchors_for(sym: dict, ok_names: set[str]) -> dict:
    """Machine-usable anchors mined out of a symbol's prose note."""
    note = str(sym.get("note") or "")
    # Strip the boilerplate downgrade tail: it is identical across ~40 symbols
    # ("resolves mid-instruction", "Pattern stripped", ...) and every quoted
    # word inside it would become a shared, meaningless anchor.
    head = re.split(r"\[20\d\d-\d\d-\d\d[: ]", note)[0]

    strings = {m.group(1).strip() for m in _QUOTED.finditer(head)}
    strings = {s for s in strings if len(s) >= MIN_STRING_ANCHOR}

    hashes = set()
    for m in _HEX.finditer(head):
        v = int(m.group(1), 16)
        if VA_LO <= v < VA_HI or v > 0xFFFFFFFF or v < 0x10000:
            continue
        hashes.add(v)

    offsets = {int(m.group(1), 16) for m in _OFFSET.finditer(head)}
    offsets = {o for o in offsets if o >= 0x20}   # +0x8/+0x10 are everywhere

    classes = {m.group(1).rstrip(":") for m in _CLASS.finditer(head)}

    # Symbols named in the note that we can already locate today.
    callees = {n for n in ok_names if n in head and n != sym["name"]}

    vft = None
    m = _VFT_SLOT.search(head)
    if m:
        slot = int(m.group(1), 16) // 8 if m.group(1) else int(m.group(2))
        # The class the slot belongs to: the first RTTI-ish name in the note.
        for c in sorted(classes, key=len, reverse=True):
            vft = (c, slot)
            break

    return {"strings": strings, "hashes": hashes, "offsets": offsets,
            "classes": classes, "callees": callees, "vft": vft}


# An offset group this large, matched in full, is effectively an identity: the
# notes list the struct layout the routine walks (`ctx+0x198`, `count @+0x1a0`,
# `def+0x110`, ...) and no unrelated function touches the same set. Below this
# many offsets the group is not specific enough to select on its own.
MIN_OFFSET_GROUP = 5


def score(body: str, calls: set[int], a: dict, ok_addr: dict[str, int]) -> dict:
    hit_s = sum(1 for s in a["strings"] if s in body)
    hit_h = sum(1 for h in a["hashes"] if f"0x{h:x}" in body)
    hit_c = sum(1 for c in a["callees"]
                if c in ok_addr and ok_addr[c] in calls)
    hit_o = sum(1 for o in a["offsets"] if f"0x{o:x}" in body)
    frac_o = hit_o / len(a["offsets"]) if a["offsets"] else 0.0

    strong = hit_s * 4 + hit_h * 4 + hit_c * 3
    # A big, near-complete offset group is promoted to a STRONG anchor. This is
    # what cracks the ~30 symbols whose notes quote no string and no class hash
    # but do spell out the struct they walk: MapCtx_LinkPairedSpawners matched
    # 6/6 of its offsets and 1/8 of its neighbour's, which separates two
    # adjacent functions that no string could tell apart.
    if len(a["offsets"]) >= MIN_OFFSET_GROUP and frac_o >= 0.8:
        strong += 4 * frac_o
    weak = 2 * frac_o if frac_o >= 0.5 else 0.0
    return {"s": hit_s, "h": hit_h, "c": hit_c, "o": hit_o,
            "frac_o": round(frac_o, 2), "strong": round(strong, 2),
            "total": round(strong + weak, 2)}


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the hand-confirmed relocations + demotions")
    ap.add_argument("--apply-shortlist", action="store_true",
                    help="ALSO write unconfirmed scorer winners (unsafe)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", help="comma-separated symbol names")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--margin", type=float, default=3.0,
                    help="winner must beat runner-up by this much")
    args = ap.parse_args()

    print(assert_corpus_matches_exe())

    doc = json.loads(SYM.read_text())
    corpus = Corpus()
    vfts = corpus.vftables()

    ok_addr: dict[str, int] = {}
    claimed: dict[int, str] = {}
    for s in doc["symbols"]:
        raw = str(s.get("raw") or "")
        if raw.startswith("FUN_"):
            addr = int(raw.split("_")[1], 16)
            if s.get("status") == "ok":
                ok_addr[s["name"]] = addr
                claimed[addr] = s["name"]

    want = set(args.only.split(",")) if args.only else None
    report = []

    for s in doc["symbols"]:
        if s.get("status") != "unverified" or s.get("kind") not in ("function", "event"):
            continue
        if want and s["name"] not in want:
            continue
        # A structured locator, where one exists, beats every heuristic below:
        # it is what the person who found the symbol recorded as identifying
        # it, not a guess reconstructed from prose. Measured on the 30 symbols
        # that carry one, locators resolve exactly 67% of the time and put the
        # right answer in the shortlist 87% of the time, against 25%/39% for
        # mining the same symbols' notes.
        loc = s.get("locator")
        if loc:
            try:
                from symbol_locate import Build, resolve_locator  # noqa: PLC0415
            except ImportError:
                pass
            else:
                global _BUILD
                if _BUILD is None:
                    _BUILD = Build(CORPUS, VFTABLES)
                hits, why = resolve_locator(_BUILD, loc, ok_addr)
                free = [h for h in hits if h not in claimed]
                if len(free) == 1:
                    report.append({
                        "name": s["name"], "stale_raw": s.get("raw"),
                        "verdict": "locator", "new_raw": f"FUN_{free[0]:x}",
                        "evidence": why,
                    })
                    continue

        a = anchors_for(s, set(ok_addr))
        entry = {
            "name": s["name"], "stale_raw": s.get("raw"),
            "anchors": {"strings": sorted(a["strings"]),
                        "hashes": [hex(h) for h in sorted(a["hashes"])],
                        "callees": sorted(a["callees"]),
                        "offsets": [hex(o) for o in sorted(a["offsets"])],
                        "vft": a["vft"]},
        }

        # 1. vftable slot — an identity, so it short-circuits the scoring.
        if a["vft"]:
            cls, slot = a["vft"]
            # Exact class name first: `oCDtEntityCpnt3DBookTabController` also
            # *contains* `...BookController`, and taking the substring match
            # resolved slot 28 of the wrong table (to `_guard_check_icall`).
            ordered = sorted(vfts.items(),
                             key=lambda kv: (kv[0] != cls, cls not in kv[0], len(kv[0])))
            for name, recs in ordered:
                if name != cls and cls not in name:
                    continue
                for rec in recs:
                    if slot < len(rec["slots"]):
                        entry_slot = rec["slots"][slot]
                        # CFG thunks and pure-virtual stubs fill unused slots in
                        # every table; they are never the routine being sought.
                        if entry_slot["name"] in ("_guard_check_icall", "_purecall"):
                            continue
                        va = int(entry_slot["va"], 16)
                        if va in corpus.code and claimed.get(va) is None:
                            entry["verdict"] = "vftable"
                            entry["new_raw"] = f"FUN_{va:x}"
                            entry["evidence"] = f"{name}::vftable[{slot}]"
                            break
                if "new_raw" in entry:
                    break

        if "new_raw" not in entry:
            if not (a["strings"] or a["hashes"] or a["callees"] or a["offsets"]):
                entry["verdict"] = "no-anchors"
            else:
                cands = []
                for addr, body in corpus.code.items():
                    sc = score(body, corpus.calls[addr], a, ok_addr)
                    if sc["strong"] <= 0:
                        continue
                    cands.append((sc["total"], addr, sc))
                cands.sort(key=lambda t: (-t[0], t[1]))
                entry["candidates"] = [
                    {"addr": f"0x{c[1]:x}", "owner": claimed.get(c[1]), **c[2]}
                    for c in cands[:args.top]
                ]
                free = [c for c in cands if c[1] not in claimed]
                if not free:
                    entry["verdict"] = "no-match" if not cands else "all-claimed"
                elif len(free) == 1 or free[0][0] - free[1][0] >= args.margin:
                    entry["verdict"] = "unique"
                    entry["new_raw"] = f"FUN_{free[0][1]:x}"
                else:
                    entry["verdict"] = "ambiguous"

        report.append(entry)

    applied = 0
    if args.apply:
        by_name = {x["name"]: x for x in doc["symbols"]}
        # CONFIRMED runs after DEMOTE, so a name in both would silently undo
        # its own demotion — which is exactly what happened the first time
        # InitialLoading_SpawnMagicalObjects was reclassified.
        clash = set(CONFIRMED) & set(DEMOTE)
        if clash:
            raise SystemExit(f"name in both CONFIRMED and DEMOTE: {sorted(clash)}")

        # Demotions first: a demoted symbol releases its address, which is what
        # lets the confirmed table hand that address to its real owner.
        for name, why in DEMOTE.items():
            sym = by_name.get(name)
            if sym is None or sym.get("status") == "unverified":
                continue
            sym["status"] = "unverified"
            sym["note"] = str(sym.get("note") or "") + " [" + why + "]"
            applied += 1

        for name, (raw, why) in CONFIRMED.items():
            sym = by_name.get(name)
            if sym is None:
                continue
            sym["raw"] = raw
            sym["status"] = "ok"
            sym.pop("anchor", None)   # a stale anchor offset outlives the raw
            sym["note"] = (str(sym.get("note") or "")
                           + f" [RELOCATED to {raw} 2026-08-09, hand-confirmed: {why}]")
            applied += 1

        for name, why in ALIASES.items():
            sym = by_name.get(name)
            if sym is None or why in str(sym.get("note") or ""):
                continue
            sym["note"] = str(sym.get("note") or "") + " [" + why + "]"

        # Scorer winners are NOT written by default. Three of the current
        # "unique"/"vftable" picks are demonstrably wrong (a caller instead of
        # the callee, a CFG stub shared by every vtable), and writing them
        # would manufacture exactly the false-ok state this tool exists to
        # clean up. Promote a shortlist entry by reading it and adding it to
        # CONFIRMED with its evidence.
        if args.apply_shortlist:
            for e in report:
                if e.get("verdict") not in ("vftable", "unique"):
                    continue
                if e["name"] in CONFIRMED:
                    continue
                sym = by_name[e["name"]]
                sym["raw"] = e["new_raw"]
                sym["status"] = "ok"
                sym["note"] = (str(sym.get("note") or "")
                               + f" [RELOCATED {e['stale_raw']} -> {e['new_raw']} by "
                                 f"tools/relocate_stale_symbols.py ({e['verdict']}), "
                                 f"NOT hand-confirmed.]")
                applied += 1
        SYM.write_text(json.dumps(doc, indent=1) + "\n")

    if args.json:
        print(json.dumps(report, indent=1))
    else:
        for e in report:
            new = e.get("new_raw", "")
            print(f"{e['verdict']:12} {e['name']:38} {e['stale_raw']} -> {new}")
            for c in e.get("candidates", []):
                own = f" [owned by {c['owner']}]" if c["owner"] else ""
                print(f"             {c['addr']} total={c['total']} "
                      f"str={c['s']} hash={c['h']} call={c['c']} "
                      f"off={c['o']}({c['frac_o']}){own}")
        buckets: dict[str, int] = {}
        for e in report:
            buckets[e["verdict"]] = buckets.get(e["verdict"], 0) + 1
        print("\n" + ", ".join(f"{k}={v}" for k, v in sorted(buckets.items())))
        if args.apply:
            print(f"applied {applied} relocation(s) to {SYM}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
