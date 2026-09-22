#!/usr/bin/env python3
"""Mine every shipped enemy into one catalog: stats, tribe, biome, tags.

Writes ``data/enemy_catalog.json``, which backs the enemy encyclopedia page in
the docs. Run it after a game patch; ``--check`` fails when the committed file
is stale.

WHERE AN ENEMY'S NUMBERS ACTUALLY LIVE
--------------------------------------
Not on the enemy definition. ``oCDtEnemyDefinition`` spends its 0x350 bytes on
tags, tier curves and resource refs (see docs/_re/kinds/enemies.md); it points
at an ``oCEntitySettings``, and the stats are authored *there* — as named
value overrides of the form::

    [Value] <Parent>\\Attributes\\Raw Max Health

...which is the same ``[Value] Parent\\Cpnt\\Field`` override mechanism the
entity-append work documented. The record that follows the name opens with two
marks -- a header and the payload -- and the payload carries a u32 type tag at
+8 (0 = float) and the f32 at +16. The payload mark's own tag is a per-FILE
index, not a constant, so it is the POSITION that identifies it.

INHERITANCE IS THE WHOLE PROBLEM
--------------------------------
Almost no enemy sets its own health. ``Gnoll_Hunter`` inherits from
``Gnoll_Model``, which inherits from ``Enemy_Model``, and only ``Gnoll_Model``
carries a ``Raw Max Health``. So a value is resolved by walking the parent
chain and taking the NEAREST definition of it, exactly as the engine does --
and the catalog records which ancestor supplied it, because "125 HP, inherited
from Gnoll_Model" and "125 HP, authored here" are different facts for a modder
deciding what to edit.

WHAT THIS DELIBERATELY DOES NOT CLAIM
-------------------------------------
* **Booleans are skipped.** ``Is Stagger Resistant`` and friends are authored
  the same way but encode under type tag 2. Read as a 4-byte float like the
  numbers, they give one "decodable" instance — because the value is ONE byte
  at +16 with the next mark at +17, so a float read swallows the mark. Read as
  that byte, all 41 overrides decode cleanly (2026-09-22): 39 are 0, and 2 are 1
  (``Hands_Nightmares_Hand_Model``, ``Boss_Roc_Bird``). Still not emitted: the
  default lives in ``Character_Common``'s *declaration*, which does not parse
  as an override, so an explicit 0 cannot be told from "same as the default".
  Note it does NOT explain the Tentacle Master's stagger (he reads 0) — see
  ``STAGGER_NOTES``. Float attributes cross-check cleanly (crabs 70, gnolls
  125, ogres 300, Baba Yaga 1000) and are all this emits.
* **These are BASE values; the run's scaling is mined separately** by
  :func:`scaling` into the JSON's ``scaling`` key. It lives in
  ``Common_Settings/Group_Scaling``: a ``Chapter Max Health Multiplier
  Selector`` switching on the current chapter, whose entries are per-chapter
  selectors switching on the game difficulty; a setter writes the result into
  the ``Chapter_Scaling_Enemies_Max_Health_Factor`` global, whose shipped 1.0 is
  only its initial value. Corruption (tainted) ratios are on ``Enemy_Model``.
  The ``NGP_*`` globals are separate New Game Plus knobs and do ship at 0.0.
  (A version of this docstring once said the scaling was NOT in the corpus. It
  was wrong: that came from searching cooked files with plain ``grep``, which on
  the dev machine is ugrep and silently skips binary files. Use ``grep -a``.)"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rsmm.engine import cooked as _cooked  # noqa: E402
from rsmm.engine import enemy_pools as EP  # noqa: E402
from rsmm.engine import entity_components as EC  # noqa: E402
from rsmm.engine.talent_values import class_names as _class_names  # noqa: E402

OUT = REPO / "data" / "enemy_catalog.json"
DOCS_PAGE = (
    REPO / "apps" / "docs" / "src" / "content" / "docs" / "reference" / "enemy-catalog.md"
)
MIRROR = REPO / "data" / "uncooked"

MARK_BYTES = b"\x11\x11\xbb\xaa"
# The payload mark is the SECOND after the name; its tag is a per-file index.
TYPE_F32 = 0

# Float attributes worth cataloguing, in display order. Anything not in this
# list is either a boolean (see the module docstring) or a rendering detail.
ATTRS: tuple[tuple[str, str], ...] = (
    ("Raw Max Health", "health"),
    ("Stagger Max Points", "stagger_points"),
    ("Collision Radius", "collision_radius"),
    ("Character Mesh Scale", "mesh_scale"),
    ("Default Resistance", "resistance"),
)

MAX_DEPTH = 12

# Where the walk STOPS. `Character_Common` is the shared base of every hero,
# enemy and NPC, and it does not *override* these attributes -- it DECLARES
# them, in a record of a different shape whose payload sits under the first
# mark rather than the second. Reading it as though it were an override yields
# junk (a collision radius of 0 for six enemies, which is what exposed this).
# So anything that reaches this far authored nothing, and the honest answer is
# "inherits the default", not a number.
DEFAULT_BASES = frozenset({"Character_Common", "Local_Hero_Proximity_Tester"})


#: Directory names that identify a biome, mapped to the pool key the rest of
#: the catalog uses. The cooked tree spells Dark Hills both ways depending on
#: whether it is a level or an entity-settings path, which is why this is a
#: lookup rather than a `replace("_", "")`.
_BIOME_DIRS = {
    "DarkHills": "Dark_Hills",
    "Dark_Hills": "Dark_Hills",
    "Storm_Island": "Storm_Island",
    "Avalon": "Avalon",
    "Baba_Yaga_Map": "Baba_Yaga_Map",
    "Baba_Yaga_House": "Baba_Yaga_Map",
}


def boss_arenas(boss_flags: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    """``boss id -> {"biome", "arena"}`` for the bosses a biome places.

    A boss definition carries a per-boss flag (``BossCrab``, ``Boss_White_Lady``)
    and the ARENA that summons it is the thing that references that flag —
    `src/rsmm/sdk/kinds/bosses.py` rests on the same fact, and
    `tests/test_boss_kind.py` asserts it. Here the reference is used in the
    other direction: whichever file names the flag tells us where the fight
    happens, and its path carries the biome.

    Excludes `*/Enemies/*` (the boss's own definition and its tribe model name
    the flag too) and reads the biome only from a biome-specific directory, so
    a tribe def or a bark manager contributes nothing. Fails CLOSED: a boss
    whose flag lands in two biomes, or in none, is left unattributed and
    rendered under the chapter/quest heading instead of being guessed at.
    """
    if not boss_flags:
        return {}
    tokens = {f for fl in boss_flags.values() for f in fl}
    if not tokens:
        return {}
    rx = re.compile(
        rb"(?<![A-Za-z0-9_])(" + b"|".join(re.escape(t.encode()) for t in sorted(tokens))
        + rb")(?![A-Za-z0-9_])"
    )

    hits: dict[str, set[tuple[str, str]]] = {t: set() for t in tokens}
    for root in ("Ot", "Definitions", "EntitySettings"):
        base = MIRROR / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.gen"):
            posix = path.as_posix()
            if "UsedRscCache" in path.name or "/Enemies/" in posix:
                continue
            biome = next(
                (_BIOME_DIRS[part] for part in path.parts if part in _BIOME_DIRS), None
            )
            if biome is None:
                continue
            try:
                blob = path.read_bytes()
            except OSError:
                continue
            for m in set(rx.findall(blob)):
                hits[m.decode()].add((biome, path.stem.split(".")[0]))

    out: dict[str, dict[str, str]] = {}
    for boss, flags in boss_flags.items():
        found = {h for f in flags for h in hits.get(f, ())}
        biomes = {b for b, _ in found}
        if len(biomes) != 1:
            continue  # unplaced, or ambiguous — say nothing
        biome = biomes.pop()
        arena = sorted(a for b, a in found if b == biome)[0]
        out[boss] = {"biome": biome, "arena": arena}
    return out



# --------------------------------------------------------------- run scaling
#
# Everything below reads SHIPPED DATA. An earlier version of this page said the
# scaling was not in the corpus; that conclusion came from searching with the
# system `grep`, which on this machine is ugrep and silently skips binary files,
# so every cooked `.gen` read as "no match". The values were there all along.

SCALING_ENTITY = "EntitySettings/Common_Settings/Group_Scaling.entity.ot.EntitySettingsResource.gen"
ENEMY_MODEL = "EntitySettings/Enemies/NPC_Common/Enemy_Model.entity.ot.EntitySettingsResource.gen"
TUMOR_ENTITY = (
    "EntitySettings/Objects/Nightmare_Tumor/Nightmare_Tumor.entity.ot.EntitySettingsResource.gen"
)

#: What a selector switches on. A `oCEntityCpntValuePicker` names the value by
#: CRC; these two labels are from the engine's own registration table
#: (`data/symbols.json::EntityValueRegistry_RegisterAll` and the key table on
#: `g_GlobalEntityValueSceneContext_Tester_vftable`). An unknown key is rendered
#: as hex rather than guessed at.
SWITCH_KEYS = {0x181D17FD: "chapter", 0x18700873: "difficulty"}

_T_F32, _T_INT = 0, 1


def _union_values(payload: bytes, union_idx: int) -> list[float | int]:
    """Every `oCEntityValueUnion` in one section, in file order (floats and ints)."""
    tag = MARK_BYTES + struct.pack("<I", union_idx)
    out: list[float | int] = []
    pos = 0
    while (at := payload.find(tag, pos)) >= 0:
        typ = struct.unpack_from("<I", payload, at + 8)[0]
        if typ == _T_F32:
            out.append(round(struct.unpack_from("<f", payload, at + 16)[0], 4))
        elif typ == _T_INT:
            out.append(struct.unpack_from("<i", payload, at + 16)[0])
        pos = at + 8
    return out


def _labelled_sections(raw: bytes):
    """``(class, label, payload)`` for each top-level section of a cooked entity.

    The label is the section's own length-prefixed node name, which sits a fixed
    distance in after the section's GUID mark.
    """
    names = _class_names(raw) or []
    for sec in _cooked.parse(raw).sections:
        p = sec.payload
        if len(p) < 4:
            continue
        ci = struct.unpack_from("<I", p, 0)[0]
        cls = names[ci] if ci < len(names) else ""
        m = re.search(rb"([\x04-\x7f])\x00\x00\x00([A-Za-z][A-Za-z0-9 _]{3,80})", p[:260])
        label = m.group(2).decode() if m and m.group(1)[0] == len(m.group(2)) else ""
        yield cls, label, p, names


def _read(rel: str) -> bytes | None:
    path = MIRROR / rel
    return path.read_bytes() if path.exists() else None


def scaling() -> dict[str, object]:
    """The run's enemy scaling, mined from `Group_Scaling` and `Enemy_Model`.

    Returns ``{}`` when the mirror lacks those entities, so a partial corpus
    renders no scaling section rather than a wrong one.
    """
    raw = _read(SCALING_ENTITY)
    if raw is None:
        return {}
    out: dict[str, object] = {"selectors": {}, "groups": {}}
    selectors: dict[str, dict] = out["selectors"]  # type: ignore[assignment]
    groups: dict[str, list] = out["groups"]  # type: ignore[assignment]
    for cls, label, p, names in _labelled_sections(raw):
        uidx = names.index("oCEntityValueUnion")
        if cls == "oCEntityCpntValueSwitchSelectorSettings":
            picker = MARK_BYTES + struct.pack("<I", names.index("oCEntityCpntValuePicker"))
            at = p.find(picker)
            key = struct.unpack_from("<I", p, at + 10)[0] if at >= 0 else 0
            vals = _union_values(p, uidx)
            # layout: one leading int, then (int key, float value) per entry
            entries = [v for v in vals[1:] if isinstance(v, float)]
            selectors[label] = {
                "switch": SWITCH_KEYS.get(key, f"0x{key:08x}"),
                "values": entries,
            }
        elif cls == "oCDtEntityCpntGroupLevelSettings":
            groups[label] = _union_values(p, uidx)

    model = _read(ENEMY_MODEL)
    if model is not None:
        tainted: dict[str, float] = {}
        for _cls, label, p, names in _labelled_sections(model):
            if label in ("Tainted HP Increase Ratio", "Tainted Damage Increase Ratio",
                         "Tainted Stagger Increase Ratio"):
                vals = _union_values(p, names.index("oCEntityValueUnion"))
                if vals and isinstance(vals[0], float):
                    tainted[label] = vals[0]
            elif label == "Tainted Mesh Scale Multiplier Operand":
                vals = [v for v in _union_values(p, names.index("oCEntityValueUnion"))
                        if isinstance(v, float)]
                if vals:
                    tainted[label] = vals[0]
        out["tainted"] = tainted

    tumor = _read(TUMOR_ENTITY)
    if tumor is not None:
        for _cls, label, p, names in _labelled_sections(tumor):
            if label == "Reduce Boss Health Ratio Value":
                vals = _union_values(p, names.index("oCEntityValueUnion"))
                if vals:
                    out["tumor_boss_health_ratio"] = vals[0]
    return out


def mirror_path(decoded: str) -> Path | None:
    """`Enemies\\Gnoll\\Gnoll_Hunter.entity.ot` -> its file in data/uncooked."""
    rel = decoded.replace("\\", "/")
    if not rel.lower().endswith(".entity.ot"):
        return None
    p = MIRROR / "EntitySettings" / f"{rel}.EntitySettingsResource.gen"
    return p if p.exists() else None


def read_attr(raw: bytes, attr: str) -> float | None:
    """The float an entity authors for `attr`, or None when it does not.

    The record after the name opens with two marks: a header and the payload.
    The payload's tag is a per-FILE index (44 in Gnoll_Model, 59 in Ogres_Model),
    so keying on a constant tag silently found nothing in most files -- it is
    the *position* that is stable. Type at +8, value at +16.
    """
    pat = re.compile(rb"\[Value\] [A-Za-z0-9_]+\\Attributes\\" + re.escape(attr.encode()))
    for m in pat.finditer(raw):
        tail = raw[m.end() : m.end() + 320]
        marks: list[int] = []
        start = 0
        while len(marks) < 2:
            k = tail.find(MARK_BYTES, start)
            if k < 0 or k + 24 > len(tail):
                break
            marks.append(k)
            start = k + 4
        if len(marks) < 2:
            continue
        k = marks[1]
        if struct.unpack_from("<I", tail, k + 8)[0] != TYPE_F32:
            continue  # a bool or another payload type: not ours to read
        val = struct.unpack_from("<f", tail, k + 16)[0]
        # Reject anything that is not a finite, sane authored number: a misparse
        # reads adjacent marker bytes and yields ~1e30 or a denormal.
        if val != val or abs(val) > 1e7:
            continue
        return round(val, 4)
    return None


def chain(decoded: str) -> list[str]:
    """`decoded` followed by its ancestors, nearest first."""
    out: list[str] = []
    seen: set[str] = set()
    cur = decoded
    for _ in range(MAX_DEPTH):
        if not cur or cur in seen or short(cur) in DEFAULT_BASES:
            break
        seen.add(cur)
        out.append(cur)
        p = mirror_path(cur)
        if p is None:
            break
        try:
            parents = EC.parents(p.read_bytes())
        except (OSError, ValueError, IndexError, struct.error):
            break  # an entity whose parent list will not parse ends the walk
        if not parents:
            break
        cur = parents[0]
    return out


def resolve(decoded: str) -> dict[str, dict[str, object]]:
    """Every catalogued attribute, resolved through the inheritance chain."""
    found: dict[str, dict[str, object]] = {}
    for anc in chain(decoded):
        p = mirror_path(anc)
        if p is None:
            continue
        raw = p.read_bytes()
        for attr, field in ATTRS:
            if field in found:
                continue
            val = read_attr(raw, attr)
            if val is not None:
                found[field] = {"value": val, "from": short(anc)}
    return found


def short(decoded: str) -> str:
    """`Enemies\\Gnoll\\Gnoll_Model.entity.ot` -> `Gnoll_Model`."""
    return decoded.replace("\\", "/").rsplit("/", 1)[-1].split(".entity")[0]


def _is_boss(row: dict) -> bool:
    """Same rule as :func:`rank_of`, usable on a raw catalog row."""
    tokens = set(str(row["id"]).split("_"))
    flags = {str(f).lower() for f in row.get("flags") or []}
    return "Boss" in tokens or "boss" in flags or "chapterboss" in flags


def enemy_flags(enemy_id: str) -> list[str]:
    """Tags off the enemy definition, when the mirror decoded one."""
    p = MIRROR / "Definitions" / "Enemies" / f"{enemy_id}.enemydef.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    flags = d.get("flags") or []
    return [str(f) for f in flags if isinstance(f, str)]


def build() -> dict[str, object]:
    index = EP.enemy_index()
    rows: list[dict[str, object]] = []
    for enemy_id in sorted(index):
        rec = index[enemy_id]
        entity = str(rec.get("entity") or "")
        row: dict[str, object] = {
            "id": enemy_id,
            "entity": short(entity) if entity else None,
            "tribe": rec.get("tribe"),
            "biome": rec.get("biome"),
            "spawn_weight": rec.get("weight"),
            "flags": enemy_flags(enemy_id),
        }
        row["stats"] = resolve(entity) if entity else {}
        rows.append(row)

    # A boss's selecting flag is the one no other enemy carries: that isolates
    # `BossCrab` from `Boss`/`ChapterBoss`/role tags without a hand list, and it
    # is the same flag the boss kind swaps on.
    flag_count: dict[str, int] = {}
    for r in rows:
        for f in r["flags"]:  # type: ignore[union-attr]
            flag_count[f] = flag_count.get(f, 0) + 1
    boss_flags = {
        str(r["id"]): [f for f in r["flags"] if flag_count[f] == 1]  # type: ignore[union-attr]
        for r in rows
        if _is_boss(r)
    }
    arenas = boss_arenas(boss_flags)
    for r in rows:
        r["boss_arena"] = arenas.get(str(r["id"]))
    return {
        "scaling": scaling(),
        "_doc": (
            "Every shipped enemy definition with its resolved BASE stats. Mined by "
            "tools/mine_enemy_catalog.py from the cooked corpus; stats come from "
            "[Value] <Parent>\\Attributes\\<name> overrides on the referenced entity, "
            "resolved through the entity inheritance chain ('from' names the ancestor "
            "that authored the value). These are BASE numbers as shipped. 'scaling' holds "
            "the run's multipliers, mined from Group_Scaling (chapter x difficulty health "
            "and damage, stagger by chapter, the scaling groups) and Enemy_Model (the "
            "tainted/corruption ratios). Boolean attributes are deliberately absent -- "
            "see the tool's docstring."
        ),
        "source": EP.corpus_source(),
        "enemies": rows,
    }


RANK_PREFIXES = ("Standard_", "Elite_", "Boss_")
RANK_ORDER = {"Boss": 0, "Elite": 1, "Standard": 2, "Minion": 3}

# Biomes in the order a run meets them, then the catch-alls. A biome absent
# from the data is simply skipped, so a new one shows up under "Elsewhere"
# rather than being silently dropped.
BIOME_ORDER = ("Dark_Hills", "Storm_Island", "Avalon", "Baba_Yaga_Map", "Common")
BIOME_TITLES = {
    "Dark_Hills": "Dark Hills",
    "Storm_Island": "Storm Island",
    "Avalon": "Avalon",
    "Baba_Yaga_Map": "Baba Yaga's realm",
    "Common": "Any biome",
}

# Tags that carry no information in a table: the rank is already a column, and
# 75 of the tags in the corpus occur exactly once because they are just the
# enemy naming itself ("MudCrab" on the Mud Crab).
RANK_TAGS = {"standard", "elite", "boss", "chapterboss"}


def rank_of(row: dict) -> str:
    """Standard / Elite / Boss / Minion.

    Matched on ID *tokens*, not on a prefix: `Baba_Yaga_Boss` and `Knight_Boss`
    carry the word at the end, and a prefix-only test ranked the game's final
    boss as a minion.
    """
    tokens = set(str(row["id"]).split("_"))
    flags = {f.lower() for f in row.get("flags") or []}
    if "Boss" in tokens or "boss" in flags or "chapterboss" in flags:
        return "Boss"
    if "Elite" in tokens or "elite" in flags:
        return "Elite"
    if "Standard" in tokens or "standard" in flags:
        return "Standard"
    return "Minion"


def display_name(row: dict) -> str:
    """`Standard_Undead_Hog_Reaper` -> `Undead Hog Reaper`."""
    eid = str(row["id"])
    for p in RANK_PREFIXES:
        if eid.startswith(p):
            eid = eid[len(p) :]
            break
    # `Baba_Yaga_Boss` carries the rank at the END; the Rank column already
    # says it, so drop it there too rather than printing "Baba Yaga Boss | Boss".
    if eid.endswith("_Boss") and len(eid) > len("_Boss"):
        eid = eid[: -len("_Boss")]
    return eid.replace("_", " ")


def num(row: dict, field: str) -> str:
    rec = (row.get("stats") or {}).get(field)
    if not rec:
        return "—"
    return f"{rec['value']:g}"


def health_of(row: dict) -> float | None:
    rec = (row.get("stats") or {}).get("health")
    return float(rec["value"]) if rec else None


def source_note(row: dict, field: str) -> str:
    rec = (row.get("stats") or {}).get(field)
    if not rec:
        return ""
    return "" if rec["from"] == row.get("entity") else str(rec["from"])


def useful_tags(row: dict, common: set[str]) -> str:
    tags = [
        f
        for f in (row.get("flags") or [])
        if f.lower() not in RANK_TAGS and f in common
    ]
    return ", ".join(f"`{t}`" for t in tags) or "—"


def _sort_key(row: dict):
    """Heaviest first, then by rank, then alphabetically."""
    hp = health_of(row)
    return (-(hp if hp is not None else -1), RANK_ORDER.get(row["_rank"], 9), row["_name"])


def _table(
    rows: list[dict],
    common: set[str],
    *,
    show_tribe: bool = True,
    show_rank: bool = True,
    show_share: bool = False,
) -> str:
    """Render one enemy table.

    Deliberately narrower than the JSON: `mesh_scale` is the model's visual
    scale rather than anything you can feel, and `resistance` carries two
    distinct values in the whole corpus (0 for 35 enemies, 1 for the four
    crabs, unauthored for the other 42) — as columns they cost every table two
    slots of width to say almost nothing. Both are still in
    `data/enemy_catalog.json` for tooling.

    `show_rank` is off wherever the section already fixes it, so the Bosses
    table does not carry a column reading "Boss" 14 times.
    """
    # A biome table answers "what will I fight", so it leads with what the camp
    # roll picks most; every other table keeps heaviest-first.
    if show_share:
        ordered = sorted(
            rows, key=lambda r: (-float(r.get("spawn_weight") or 0), _sort_key(r))
        )
    else:
        ordered = sorted(rows, key=_sort_key)
    # A column of nothing but dashes is width spent on no information — the
    # Bosses table carries no shared tags at all, so it printed 14 of them.
    show_tags = any(useful_tags(r, common) != "—" for r in ordered)
    # Share is each enemy's slice of THIS table's spawn weight, so it only means
    # something for a table that is one biome's pool: across biomes, or for
    # scripted placements, it is a number with no roll behind it.
    total = sum(float(r.get("spawn_weight") or 0) for r in ordered) if show_share else 0.0

    head = ["Enemy"]
    if show_rank:
        head.append("Rank")
    if show_tribe:
        head.append("Tribe")
    head += ["HP", "Stagger"]
    if show_share:
        head.append("Share")
    if show_tags:
        head.append("Tags")
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in ordered:
        cells = [r["_name"]]
        if show_rank:
            cells.append(r["_rank"])
        if show_tribe:
            cells.append(str(r.get("tribe") or "—").replace("_", " "))
        cells += [
            num(r, "health"),
            _stagger(r),
        ]
        if show_share:
            w_ = float(r.get("spawn_weight") or 0)
            pct = 100 * w_ / total if total and w_ else 0.0
            cells.append("—" if not pct else "<1%" if pct < 1 else f"{pct:.0f}%")
        if show_tags:
            cells.append(useful_tags(r, common))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


#: Bosses whose stagger is scripted, so the authored `Stagger Max Points` is not
#: how the fight goes. OBSERVED IN PLAY, not mined — and deliberately so: the
#: mechanic lives in behaviour, not in an attribute. `Is Stagger Resistant` was
#: checked and does not carry it (it reads 0 on the Tentacle Master, like 38
#: other overrides). Keep entries player-confirmed; this is not a place to guess.
STAGGER_NOTES: dict[str, str] = {
    "Boss_Tentacle_Master": (
        "is not staggered by stagger damage: he is staggered once all of his "
        "tentacles are destroyed. His entity still authors 200 stagger points, "
        "which the fight does not use."
    ),
}


def _stagger(r: dict) -> str:
    """Stagger cell — `n/a` where the fight does not use the authored points."""
    return "n/a" if r["id"] in STAGGER_NOTES else num(r, "stagger_points")


def _boss_table(rows: list[dict]) -> str:
    """Bosses with the arena that summons them — the file the boss kind swaps."""
    out = ["| Boss | HP | Stagger | Arena |", "|---|---|---|---|"]
    for r in sorted(rows, key=_sort_key):
        arena = (r.get("boss_arena") or {}).get("arena")
        out.append(
            f"| {r['_name']} | {num(r, 'health')} | {_stagger(r)} "
            f"| {f'`{arena}`' if arena else '—'} |"
        )
    notes = [
        f"**{r['_name']}** {STAGGER_NOTES[r['id']]}"
        for r in sorted(rows, key=_sort_key)
        if r["id"] in STAGGER_NOTES
    ]
    if notes:
        out.append("")
        out.extend(notes)
    return "\n".join(out)


def _inherited_note(rows: list[dict]) -> str:
    srcs = sorted({f"`{s}`" for r in rows if (s := source_note(r, "health"))})
    if not srcs:
        return ""
    return f"Health inherited from {', '.join(srcs)}."



def _chapter_rows(sel: dict, stat: str) -> list[tuple[int, list[float]]]:
    """``[(chapter, per-difficulty values)]`` for one stat, in chapter order."""
    rows = []
    n = 1
    while (s := sel.get(f"Chapter {n} {stat} Multiplier Selector")) is not None:
        rows.append((n, list(s["values"])))
        n += 1
    return rows


def _render_scaling(w, sc: dict) -> None:
    """How a base value becomes the number you fight, all read from shipped data."""
    sel = sc.get("selectors") or {}
    w("## How enemies get tougher")
    w("")
    if not sel:
        w("The scaling setup (`Group_Scaling`) was not in the corpus this page was built")
        w("from, so the multipliers are not shown.")
        w("")
        return

    w("Every number above is a base value. During a run the game scales it from one")
    w("setup in the data, `Common_Settings/Group_Scaling`: a two-level switch that picks")
    w("a multiplier by the **current chapter**, then by the **game difficulty**.")
    w("")
    for stat, title in (("Max Health", "Health"), ("Damage", "Damage")):
        rows = _chapter_rows(sel, stat)
        if not rows:
            continue
        width = max(len(v) for _, v in rows)
        w(f"**{title} multiplier** — chapter down, difficulty across, lowest to highest:")
        w("")
        w("| Chapter | " + " | ".join(f"Difficulty {i + 1}" for i in range(width)) + " |")
        w("|---" * (width + 1) + "|")
        for n, vals in rows:
            w(f"| {n} | " + " | ".join(f"×{v:g}" for v in vals) + " |")
        w("")
    w("A standard run plays three chapters; the data defines a fourth row as well.")
    w("")

    stag = (sel.get("Chapter Stagger Multiplier Selector") or {}).get("values") or []
    common = (sel.get("Chapter Common Stagger Per Player Selector") or {}).get("values") or []
    elite = (sel.get("Chapter Elite Stagger Per Player Selector") or {}).get("values") or []
    if stag:
        w("**Stagger** scales by chapter only, and carries a per-player value chosen by")
        w("chapter. The value is named per player; the exact formula that applies it to")
        w("the party is in the game's code.")
        w("")
        w("| Chapter | Stagger multiplier | Per player (common) | Per player (elite) |")
        w("|---|---|---|---|")
        for i in range(max(len(stag), len(common), len(elite))):
            def cell(seq, i=i, fmt="×{:g}"):
                return fmt.format(seq[i]) if i < len(seq) else "—"
            w(f"| {i + 1} | {cell(stag)} | {cell(common, fmt='+{:g}')} "
              f"| {cell(elite, fmt='+{:g}')} |")
        w("")
    w("`Group_Scaling` has no per-player **health** term: health scales by chapter and")
    w("difficulty only. Every per-player value in it is a stagger value.")
    w("")

    tainted = sc.get("tainted") or {}
    if tainted:
        parts = []
        for label, noun in (("Tainted HP Increase Ratio", "health"),
                            ("Tainted Damage Increase Ratio", "damage"),
                            ("Tainted Stagger Increase Ratio", "stagger")):
            if label in tainted:
                parts.append(f"**+{tainted[label] * 100:g}%** {noun}")
        scale = tainted.get("Tainted Mesh Scale Multiplier Operand")
        if scale and scale != 1:
            parts.append(f"**{(scale - 1) * 100:g}%** larger")
        w("### Corrupted (tainted) enemies")
        w("")
        w("Defined on `Enemy_Model`, which every enemy inherits, so it applies to any")
        w("enemy that can be tainted: " + ", ".join(parts) + ".")
        w("")

    groups = sc.get("groups") or {}
    tiers = [g for g in ("Boss Enemy Group", "Elite Enemy Group", "Common Enemy Group")
             if g in groups]
    if len(tiers) >= 2:
        vals = [groups[g] for g in tiers]
        # the fields that actually set the tiers apart; the shared ones say nothing
        differ = [i for i in range(1, min(len(v) for v in vals))
                  if len({v[i] for v in vals}) > 1]
        w("### Bosses scale on their own curve")
        w("")
        w("Enemies are split into scaling groups, each with its own level curve up to")
        w(f"level {vals[0][0]}. The groups share their other rates and differ in these")
        w("coefficients, highest for bosses:")
        w("")
        w("| Group | " + " | ".join(f"Coefficient {j + 1}" for j in range(len(differ))) + " |")
        w("|---" * (len(differ) + 1) + "|")
        for g, v in zip(tiers, vals, strict=True):
            w(f"| {g.replace(' Enemy Group', '')} | "
              + " | ".join(f"{v[i]:g}" for i in differ) + " |")
        w("")
        w("What each coefficient controls is not labelled in the data. Which group an")
        w("enemy scales in is not in the data either — no file references any group —")
        w("so the game's code assigns it, most likely by rank.")
        w("")

    ratio = sc.get("tumor_boss_health_ratio")
    if ratio is not None:
        w("### Nightmare tumors")
        w("")
        w(f"Each tumor publishes a boss-health reduction ratio of **{ratio:g}**")
        w("(`Tumor_Reduce_Boss_Health_Ratio`), set by the tumor's own entity. The name")
        w("says destroying tumors weakens the boss; the rule that applies it is in the")
        w("game's code.")
        w("")

    w("### Per-chapter enemy variants")
    w("")
    w("There are none. No enemy definition carries a chapter, act or tier marker, and")
    w("the nightmare family a run meets everywhere — cultists, spiders, tentacles,")
    w("thieves — is one flat set of definitions reused in every biome. A late cultist")
    w("is the same definition as an early one; the chapter multiplier above is what")
    w("makes it hit harder.")
    w("")


def render_docs(data: dict) -> str:
    rows: list[dict] = list(data["enemies"])  # type: ignore[arg-type]
    for r in rows:
        r["_rank"] = rank_of(r)
        r["_name"] = display_name(r)

    # Stripping the rank prefix can collide: Standard_Witch_Crone and
    # Boss_Witch_Crone are both "Witch Crone", which made one of them look like
    # it appeared twice in the tables at two different totals. Only the
    # colliding names get the rank back.
    name_counts: dict[str, int] = {}
    for r in rows:
        name_counts[r["_name"]] = name_counts.get(r["_name"], 0) + 1
    for r in rows:
        if name_counts[r["_name"]] > 1:
            r["_name"] = f"{r['_name']} ({r['_rank']})"

    # A tag earns a column slot only if more than one enemy carries it.
    seen: dict[str, int] = {}
    for r in rows:
        for f in r.get("flags") or []:
            seen[f] = seen.get(f, 0) + 1
    common = {f for f, n in seen.items() if n > 1}

    tribes: dict[str, list[dict]] = {}
    for r in rows:
        tribes.setdefault(str(r.get("tribe") or "(no tribe)"), []).append(r)

    bosses = [r for r in rows if r["_rank"] == "Boss"]
    rest = [r for r in rows if r["_rank"] != "Boss"]
    by_biome: dict[str, list[dict]] = {}
    for r in rest:
        by_biome.setdefault(str(r.get("biome") or ""), []).append(r)
    unplaced = by_biome.pop("", [])

    out: list[str] = []
    w = out.append

    w("---")
    w("title: Enemy encyclopedia")
    w(
        "description: Where every enemy in the game spawns, with the base health "
        "and stagger it ships with, mined from the cooked data."
    )
    w("---")
    w("")
    # Kept deliberately: tests/test_enemy_catalog.py pins this banner, because a
    # hand-edit here is silently reverted by the next run of the tool.
    w(":::note[Generated file]")
    w("Built by `tools/mine_enemy_catalog.py` from the cooked corpus and checked in as")
    w("`data/enemy_catalog.json`. Do not edit this page by hand — re-run the tool.")
    w(":::")
    w("")
    biome_count = len([b for b in by_biome if b])
    w(
        f"**{len(rows)} enemy definitions** — {len(bosses)} bosses and "
        f"{len(rest)} others, across {len(tribes)} tribes and {biome_count} spawn pools."
    )
    w("")

    # ---------------------------------------------------------------- summary
    w("## At a glance")
    w("")
    counts = {k: sum(1 for r in rows if r["_rank"] == k) for k in RANK_ORDER}
    w("| Rank | Count | What it means |")
    w("|---|---|---|")
    w(f"| Boss | {counts['Boss']} | Chapter bosses and the arena bosses. |")
    w(f"| Elite | {counts['Elite']} | The tougher variant a camp can roll. |")
    w(f"| Standard | {counts['Standard']} | The ordinary camp and wave population. |")
    w(f"| Minion | {counts['Minion']} | Summons, eggs and adds — spawned by something else. |")
    w("")
    no_hp = [r for r in rows if health_of(r) is None]

    # ----------------------------------------------------------------- legend
    w("## How to read the tables")
    w("")
    w("| Column | What it is |")
    w("|---|---|")
    w("| **HP** | `Raw Max Health` — the base the HitPoint component starts from. |")
    w("| **Stagger** | `Stagger Max Points` — stagger absorbed before it breaks. |")
    w("| **Share** | How often the camp roll picks it: its spawn weight over the biome's total. |")
    w("| **Tags** | Definition flags that more than one enemy carries. |")
    w("")
    w("`data/enemy_catalog.json` carries three more attributes the tables leave out:")
    w("collision radius and mesh scale, which describe how big the model is rather")
    w("than how it fights, and resistance, which is 0 for every enemy that authors it")
    w("except the four crabs, which are 1.")
    w("")
    w("Biome tables list the enemies you meet most first; the others are sorted")
    w("heaviest first. `n/a` means the enemy authors the value but its fight does")
    w("not use it — the note under that table says what happens instead. A dash")
    w("means the enemy does not author that")
    w("attribute and inherits it. Where health comes from an ancestor rather than the")
    w("enemy's own entity, the ancestor is named under the table — that is the file a")
    w("mod would edit, and editing it changes **every** enemy that inherits from it.")
    w("")
    w(":::caution[A dash is not zero]")
    w(f"{len(no_hp)} enemies never author health and inherit the `Character_Common`")
    w("default, which reads as **100**. Everything with a number overrides it")
    w("somewhere in its ancestry.")
    w(":::")
    w("")

    # ------------------------------------------------------------- by biome
    w("## Where you meet them")
    w("")
    w("Grouped by the biome spawn pool that streams the entity — an enemy whose")
    w("entity is not in a biome's pool is simply not there to instantiate, whatever")
    w("its tribe says. See [Enemies](/reverse-engineering/enemies/) for the two gates.")
    w("")
    boss_by_biome: dict[str, list[dict]] = {}
    for r in bosses:
        placed = (r.get("boss_arena") or {}).get("biome")
        if placed:
            boss_by_biome.setdefault(str(placed), []).append(r)
    # A biome with a boss but no camp enemies would otherwise have no section to
    # hang the boss on, and the boss would vanish from the page entirely.
    present = set(by_biome) | set(boss_by_biome)
    ordered = [b for b in BIOME_ORDER if b in present]
    ordered += [b for b in sorted(present) if b not in BIOME_ORDER]
    for biome in ordered:
        members = by_biome.get(biome, [])
        here = boss_by_biome.get(biome, [])
        w(f"### {BIOME_TITLES.get(biome, biome.replace('_', ' '))}")
        w("")
        parts = [f"{len(members)} enemies"] if members else []
        if here:
            parts.append(f"{len(here)} boss" + ("es" if len(here) != 1 else ""))
        w(", ".join(parts) + ".")
        w("")
        if members:
            w(_table(members, common, show_share=True))
            note = _inherited_note(members)
            if note:
                w("")
                w(note)
            w("")
        if here:
            w("**Bosses fought here**")
            w("")
            w(_boss_table(here))
            w("")

    if unplaced:
        w("### Summoned and unpooled")
        w("")
        w("Not in any biome pool: adds that something else spawns, plus named enemies")
        w("placed by a specific encounter rather than by the camp generator.")
        w("")
        w(_table(unplaced, common))
        note = _inherited_note(unplaced)
        if note:
            w("")
            w(note)
        w("")

    # ------------------------------------------------------------------ bosses
    unplaced_bosses = [r for r in bosses if not (r.get("boss_arena") or {}).get("biome")]
    if unplaced_bosses:
        w("## Chapter and quest bosses")
        w("")
        w("Bosses the data does not tie to a biome: the chapter bosses, and Dullahan,")
        w("whose quest is not filed under one. Every other boss — including quest bosses")
        w("like the Roc, whose quest lives on Storm Island — is listed under the biome")
        w("it is fought in, above.")
        w("")
        w(_boss_table(unplaced_bosses))
        w("")

    # ------------------------------------------------------------- tribe index
    w("## Tribes at a glance")
    w("")
    w("A tribe groups enemies for camp generation, and it is usually also where the")
    w("shared stats live — every gnoll is 125 HP because `Gnoll_Model` says so.")
    w("")
    w("| Tribe | Biome | Members | HP | Health authored by |")
    w("|---|---|---|---|---|")
    for tribe in sorted(tribes):
        members = tribes[tribe]
        biomes = sorted({str(r["biome"]) for r in members if r.get("biome")})
        hps = sorted({h for r in members if (h := health_of(r)) is not None})
        if not hps:
            hp_s = "—"
        elif len(hps) == 1:
            hp_s = f"{hps[0]:g}"
        else:
            hp_s = f"{hps[0]:g}–{hps[-1]:g}"
        srcs = sorted({s for r in members if (s := source_note(r, "health"))})
        w(
            f"| {tribe.replace('_', ' ')} "
            f"| {', '.join(BIOME_TITLES.get(b, b.replace('_', ' ')) for b in biomes) or '—'} "
            f"| {len(members)} | {hp_s} "
            f"| {', '.join(f'`{s}`' for s in srcs) or '*own entity*'} |"
        )
    w("")

    # ------------------------------------------------------------ run scaling
    _render_scaling(w, data.get("scaling") or {})

    # ------------------------------------------------------------------ modding
    w("## Changing these numbers")
    w("")
    w("Health is not on the enemy definition — it is an entity-value override on the")
    w("`oCEntitySettings` the definition points at, so a mod that edits the `enemydef`")
    w("changes tags and spawn weights and nothing else. See")
    w("[Enemies](/reverse-engineering/enemies/) for the definition layout,")
    w("[Anatomy of an entity](/reverse-engineering/entity-anatomy/) for why the number")
    w("lives where it does, and [Custom enemies](/guides/custom-enemies/) for the")
    w("authoring path.")
    w("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the committed files are stale")
    ap.add_argument("--stats", action="store_true", help="print a coverage summary")
    args = ap.parse_args()

    if EP.corpus_source() == "none":
        print("no cooked corpus: run scripts/extract_uncooked.py or install the game")
        return 2

    data = build()
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    page = render_docs(json.loads(text))

    targets = ((OUT, text), (DOCS_PAGE, page))

    if args.check:
        stale = [p for p, want in targets if not p.exists() or p.read_text() != want]
        if stale:
            for p in stale:
                print(f"{p.relative_to(REPO)} is stale -- run {Path(__file__).name}")
            return 1
        print(f"enemy catalog up to date ({len(data['enemies'])} enemies)")
        return 0

    for p, want in targets:
        p.write_text(want)
    rows = data["enemies"]
    with_hp = sum(1 for r in rows if "health" in r["stats"])
    print(f"wrote {OUT.relative_to(REPO)}: {len(rows)} enemies, {with_hp} with resolved health")
    print(f"wrote {DOCS_PAGE.relative_to(REPO)}")

    if args.stats:
        for r in rows:
            hp = r["stats"].get("health")
            hp_s = f"{hp['value']:g} (from {hp['from']})" if hp else "-"
            print(f"  {r['id']:38s} {str(r['tribe'] or '-'):16s} {hp_s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
