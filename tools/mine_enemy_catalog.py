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
  the same way but encode under type tag 2, and a sweep of the corpus finds a
  single decodable instance -- so the reader is not trustworthy and emitting it
  would be inventing data. Float attributes cross-check cleanly (crabs 70,
  gnolls 125, ogres 300, Baba Yaga 1000) and are all this emits.
* **These are BASE values.** The run applies chapter and party-size multipliers
  on top (``Group_Scaling\\Chapter Max Health Multiplier Selector``), so the
  number here is not what a level-3 player fights.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rsmm.engine import enemy_pools as EP  # noqa: E402
from rsmm.engine import entity_components as EC  # noqa: E402

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
    return {
        "_doc": (
            "Every shipped enemy definition with its resolved BASE stats. Mined by "
            "tools/mine_enemy_catalog.py from the cooked corpus; stats come from "
            "[Value] <Parent>\\Attributes\\<name> overrides on the referenced entity, "
            "resolved through the entity inheritance chain ('from' names the ancestor "
            "that authored the value). These are base numbers: the run scales them by "
            "chapter and party size. Boolean attributes are deliberately absent -- see "
            "the tool's docstring."
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


def _table(rows: list[dict], common: set[str], *, show_tribe: bool = True) -> str:
    head = ["Enemy", "Rank"]
    if show_tribe:
        head.append("Tribe")
    head += ["HP", "Stagger", "Radius", "Scale", "Resist", "Tags"]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in sorted(rows, key=_sort_key):
        cells = [r["_name"], r["_rank"]]
        if show_tribe:
            cells.append(str(r.get("tribe") or "—").replace("_", " "))
        cells += [
            num(r, "health"),
            num(r, "stagger_points"),
            num(r, "collision_radius"),
            num(r, "mesh_scale"),
            num(r, "resistance"),
            useful_tags(r, common),
        ]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _inherited_note(rows: list[dict]) -> str:
    srcs = sorted({f"`{s}`" for r in rows if (s := source_note(r, "health"))})
    if not srcs:
        return ""
    return f"Health inherited from {', '.join(srcs)}."


def render_docs(data: dict) -> str:
    rows: list[dict] = list(data["enemies"])  # type: ignore[arg-type]
    for r in rows:
        r["_rank"] = rank_of(r)
        r["_name"] = display_name(r)

    # Stripping the rank prefix can collide: Standard_Witch_Crone and
    # Boss_Witch_Crone are both "Witch Crone", which made one of them look like
    # it appeared twice in the health ladder at two different totals. Only the
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
        "description: Every enemy the game ships — base health, stagger, size, "
        "tribe, biome and tags, mined from the cooked data."
    )
    w("---")
    w("")
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
    w("### The health ladder")
    w("")
    w("Base health only — see the caveat below. This is the whole roster sorted into")
    w("tiers, which is the quickest way to see what is actually dangerous:")
    w("")
    ladder: dict[float, list[dict]] = {}
    for r in rows:
        hp = health_of(r)
        if hp is not None:
            ladder.setdefault(hp, []).append(r)
    w("| HP | Enemies |")
    w("|---|---|")
    for hp in sorted(ladder, reverse=True):
        names = ", ".join(sorted(x["_name"] for x in ladder[hp]))
        w(f"| **{hp:g}** | {names} |")
    no_hp = [r for r in rows if health_of(r) is None]
    if no_hp:
        w(f"| *default* | {', '.join(sorted(r['_name'] for r in no_hp))} |")
    w("")

    # ----------------------------------------------------------------- legend
    w("## How to read the tables")
    w("")
    w("| Column | What it is |")
    w("|---|---|")
    w("| **HP** | `Raw Max Health` — the base the HitPoint component starts from. |")
    w("| **Stagger** | `Stagger Max Points` — stagger absorbed before it breaks. |")
    w("| **Radius** | `Collision Radius` — physical size, and how easily it is hit. |")
    w("| **Scale** | `Character Mesh Scale` — visual scale of the model. |")
    w("| **Resist** | `Default Resistance` — baseline damage resistance. |")
    w("| **Tags** | Definition flags that more than one enemy carries. |")
    w("")
    w("Tables are sorted heaviest first. A dash means the enemy does not author that")
    w("attribute and inherits it. Where health comes from an ancestor rather than the")
    w("enemy's own entity, the ancestor is named under the table — that is the file a")
    w("mod would edit, and editing it changes **every** enemy that inherits from it.")
    w("")
    w("Tags naming the enemy itself are omitted (75 of them occur exactly once,")
    w("because they are just the enemy's own name), as is the rank, which is a column.")
    w("")
    w(":::caution[These are base values, and a dash is the shared default]")
    w("The run multiplies health by chapter and party size before you ever swing at")
    w("something, so a 70 HP crab is not 70 HP in chapter 3. Read these as relative:")
    w("a gnoll is roughly twice a crab.")
    w("")
    w(f"{len(no_hp)} enemies never author health and fall through to the")
    w("`Character_Common` default, which reads as **100**. The mining deliberately")
    w("stops before `Character_Common`: it *declares* these attributes rather than")
    w("overriding them, in a record whose payload sits under a different mark, so")
    w("reading it as an override produces junk. Everything in the tables **is** mined")
    w("from a real override; everything dashed is inherited.")
    w(":::")
    w("")

    # ------------------------------------------------------------------ bosses
    w("## Bosses")
    w("")
    w(_table(bosses, common))
    note = _inherited_note(bosses)
    if note:
        w("")
        w(note)
    w("")

    # ------------------------------------------------------------- by biome
    w("## Where you meet them")
    w("")
    w("Grouped by the biome spawn pool that streams the entity — an enemy whose")
    w("entity is not in a biome's pool is simply not there to instantiate, whatever")
    w("its tribe says. See [Enemies](/reverse-engineering/enemies/) for the two gates.")
    w("")
    ordered = [b for b in BIOME_ORDER if b in by_biome]
    ordered += [b for b in sorted(by_biome) if b not in BIOME_ORDER]
    for biome in ordered:
        members = by_biome[biome]
        w(f"### {BIOME_TITLES.get(biome, biome.replace('_', ' '))}")
        w("")
        w(f"{len(members)} enemies.")
        w("")
        w(_table(members, common))
        note = _inherited_note(members)
        if note:
            w("")
            w(note)
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
            f"| {', '.join(b.replace('_', ' ') for b in biomes) or '—'} "
            f"| {len(members)} | {hp_s} "
            f"| {', '.join(f'`{s}`' for s in srcs) or '*own entity*'} |"
        )
    w("")

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
