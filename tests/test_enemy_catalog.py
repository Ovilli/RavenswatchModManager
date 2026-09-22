"""The mined enemy catalog (data/enemy_catalog.json) and its generated docs page.

Game-derived but committed, on the same terms as data/stat_keys.json: names,
tags and a handful of floats rather than game content, and it is what the
encyclopedia page in the docs is rendered from. These tests need no game exe
and no cooked corpus — they check the shape of what was mined, and that the
page and the JSON have not drifted apart.
"""

import importlib.util
import json
import re

from rsmm.engine.paths import REPO_ROOT


def _tool():
    """The miner itself, so naming rules are asserted rather than duplicated.

    An earlier version of this test re-implemented `display_name`, and drifted
    the moment the tool learned to strip a trailing `_Boss`.
    """
    path = REPO_ROOT / "tools" / "mine_enemy_catalog.py"
    spec = importlib.util.spec_from_file_location("mine_enemy_catalog", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

CATALOG = REPO_ROOT / "data" / "enemy_catalog.json"
PAGE = REPO_ROOT / "apps" / "docs" / "src" / "content" / "docs" / "reference" / "enemy-catalog.md"

# Spot values cross-checked by hand against the cooked entities they come from.
# A parser that picks the wrong mark reads adjacent marker bytes and these go
# absurd (~1e30) or vanish, so they are the first thing to break.
ANCHORS = {
    "Gnoll_Hunter": 125.0,
    "Standard_Mud_Crab": 70.0,
    "Ogre_Cyclop": 300.0,
    "Baba_Yaga_Boss": 1000.0,
    "Boss_Crab": 180.0,
}


def _rows():
    return json.loads(CATALOG.read_text())["enemies"]


def _by_id():
    return {r["id"]: r for r in _rows()}


def test_catalog_is_well_formed():
    rows = _rows()
    assert len(rows) > 60, "suspiciously small catalog"
    seen = set()
    for r in rows:
        assert r["id"] and r["id"] not in seen, f"duplicate enemy id {r['id']!r}"
        seen.add(r["id"])
        assert isinstance(r["flags"], list)
        assert isinstance(r["stats"], dict)


def test_anchor_health_values():
    rows = _by_id()
    for enemy_id, want in ANCHORS.items():
        assert enemy_id in rows, f"{enemy_id} is gone from the catalog"
        health = rows[enemy_id]["stats"].get("health")
        assert health, f"{enemy_id} lost its mined health"
        assert health["value"] == want, f"{enemy_id}: {health['value']} != {want}"


def test_stats_are_plausible_numbers():
    """A misparse reads marker bytes as a float and lands around 1e30."""
    for r in _rows():
        for field, rec in r["stats"].items():
            val = rec["value"]
            assert isinstance(val, (int, float))
            assert val == val, f"{r['id']}.{field} is NaN"
            assert 0 <= val <= 1e7, f"{r['id']}.{field} = {val} is not an authored number"
            assert rec["from"], f"{r['id']}.{field} has no source entity"


def test_most_enemies_resolve_health():
    rows = _rows()
    with_hp = sum(1 for r in rows if "health" in r["stats"])
    # 63/81 at the time of mining; the rest inherit the Character_Common
    # default. A drop here means the inheritance walk broke, which is exactly
    # how this started out (2 of 81) before the mark-position fix.
    assert with_hp >= len(rows) * 0.7, f"only {with_hp}/{len(rows)} resolved health"


def test_docs_page_matches_the_catalog():
    """Every catalogued enemy appears on the generated page, and the count agrees."""
    text = PAGE.read_text()
    rows = _rows()

    m = re.search(r"\*\*(\d+) enemy definitions\*\*", text)
    assert m, "the page lost its headline count"
    assert int(m.group(1)) == len(rows), "the page count disagrees with the catalog"

    assert "Do not edit this page by hand" in text, "the generated-file banner is gone"

    tool = _tool()
    for r in rows:
        display = tool.display_name(r)
        # Names that collide once the rank is stripped (Standard_Witch_Crone vs
        # Boss_Witch_Crone) get their rank appended, so accept either form.
        present = f"| {display} |" in text or f"| {display} (" in text
        assert present, f"{r['id']} is missing from the docs page"


def test_every_enemy_is_listed_exactly_once_in_the_body():
    """The overview must partition the roster, not sample it.

    Enemies are grouped by biome pool with an explicit bucket for the unpooled,
    and bosses sit under the biome that summons them or in the chapter/quest
    table -- so each enemy appears once in that body. A regrouping that quietly
    drops a bucket, or a boss, shows up here.
    """
    tool = _tool()
    rows = _rows()
    for r in rows:
        r["_rank"] = tool.rank_of(r)

    bosses = [r for r in rows if r["_rank"] == "Boss"]
    rest = [r for r in rows if r["_rank"] != "Boss"]
    pooled = [r for r in rest if r.get("biome")]
    unpooled = [r for r in rest if not r.get("biome")]

    assert len(bosses) + len(pooled) + len(unpooled) == len(rows)
    assert bosses, "no enemy ranks as a boss"
    assert unpooled, "the unpooled bucket vanished -- those enemies would be dropped"

    text = PAGE.read_text()
    assert "## Where you meet them" in text
    assert "### Summoned and unpooled" in text

    # Bosses are no longer one table: each sits under the biome whose arena
    # summons it, and the rest under "Chapter and quest bosses". That split is
    # exactly where a boss can fall through — attributed to a biome that has no
    # section of its own — so assert the partition directly rather than trusting
    # a heading to exist.
    boss_rows: list[str] = []
    in_boss_table = False
    for line in text.splitlines():
        if line.startswith("| Boss | HP | Stagger | Arena |"):
            in_boss_table = True
            continue
        if in_boss_table and line.startswith("|---"):
            continue
        if in_boss_table and line.startswith("| "):
            boss_rows.append(line.split("|")[1].strip())
            continue
        in_boss_table = False

    for r in rows:
        r["_name"] = tool.display_name(r)
    # the page disambiguates colliding names with the rank, as the tool does
    names = [r["_name"] for r in rows]
    for r in bosses:
        if names.count(r["_name"]) > 1:
            r["_name"] = f"{r['_name']} ({r['_rank']})"
    want = sorted(r["_name"] for r in bosses)
    assert sorted(boss_rows) == want, (
        f"boss tables list {sorted(boss_rows)}, the catalog has {want}"
    )


# Where each boss is fought, as mined from which arena references the boss's own
# flag. Hand-checked against the arena files and consistent with the SWAPPABLE
# notes in src/rsmm/sdk/kinds/bosses.py — the Wolf is the one this ADDS to them:
# bosses.py calls it "wolf den", and its den level lives under Ot/Avalon.
BOSS_BIOMES = {
    "Boss_Marsh_Ghoul": "Dark_Hills",
    "Boss_White_Lady": "Dark_Hills",
    "Boss_Crab": "Storm_Island",
    "Boss_Jinn": "Storm_Island",
    "Boss_Roc_Bird": "Storm_Island",
    "Boss_Wolf": "Avalon",
    "Boss_Witch_Crone": "Avalon",
    "Boss_Witch_Stake": "Avalon",
    "Boss_Witch_Young": "Avalon",
    "Baba_Yaga_Boss": "Baba_Yaga_Map",
}

# No biome arena references these. They must stay UNATTRIBUTED: the chapter
# bosses are not biome-placed, and Dullahan's only flag hit is a bark manager
# with no biome in its path. A heuristic that "fixed" these by name would be
# guessing, which is what the fail-closed rule in boss_arenas() exists to stop.
UNPLACED_BOSSES = {
    "Boss_Faceless_Nightmare",
    "Boss_Hand_Nightmare",
    "Boss_Tentacle_Master",
    "Boss_Dullahan_Arthur",
}


def test_bosses_are_attributed_to_the_biome_that_summons_them():
    rows = _by_id()
    for boss, biome in BOSS_BIOMES.items():
        arena = rows[boss].get("boss_arena")
        assert arena, f"{boss} lost its arena"
        assert arena["biome"] == biome, f"{boss}: {arena['biome']} != {biome}"
        assert arena["arena"], f"{boss} has a biome but no arena name"


def test_unplaced_bosses_stay_unattributed():
    rows = _by_id()
    for boss in UNPLACED_BOSSES:
        assert rows[boss].get("boss_arena") is None, (
            f"{boss} was given a biome it has no arena in: {rows[boss]['boss_arena']}"
        )


def test_every_boss_is_either_placed_or_listed_as_unplaced():
    """No boss is silently neither — a new one must be classified, not dropped."""
    tool = _tool()
    bosses = {r["id"] for r in _rows() if tool.rank_of(r) == "Boss"}
    assert bosses == set(BOSS_BIOMES) | UNPLACED_BOSSES, (
        f"unclassified bosses: {sorted(bosses - set(BOSS_BIOMES) - UNPLACED_BOSSES)}"
    )


def test_biome_shares_are_a_whole_pool():
    """Each biome table's Share column is a slice of ONE pool, so it sums to ~100%.

    Checked on the rendered page, not the JSON: share is weight/total by
    construction, so a JSON-side check would be tautological. What can actually
    break is the renderer's denominator — divide by the whole game's weight and
    every biome sums to a fraction of 100, divide per row and each is 100 alone.
    """
    text = PAGE.read_text()
    sums: dict[str, float] = {}
    section = None
    share_col = None
    for line in text.splitlines():
        if line.startswith("### "):
            section, share_col = line[4:].strip(), None
            continue
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # A header row starts every table. Re-derive the column from EACH one:
        # a biome heading holds its enemy table (with Share) and then its boss
        # table (without), and carrying the index across reads past the row.
        if cells[0] in ("Enemy", "Boss"):
            share_col = cells.index("Share") if "Share" in cells else None
            continue
        if share_col is None or section is None or cells[0].startswith("---"):
            continue
        cell = cells[share_col]
        val = 0.5 if cell == "<1%" else float(cell.rstrip("%")) if cell.endswith("%") else 0.0
        sums[section] = sums.get(section, 0.0) + val

    assert sums, "no biome table carries a Share column"
    for section, total in sums.items():
        # per-row rounding to whole percents drifts a few points over ~15 rows
        assert 90 <= total <= 110, f"{section}: shares sum to {total}%, not ~100%"


def test_scripted_stagger_is_not_shown_as_a_number():
    """The Tentacle Master is staggered by destroying his tentacles (player
    report, 2026-09-22), so the 200 his entity authors must not read as his
    stagger. The JSON keeps the real mined value; only the page says n/a."""
    tool = _tool()
    assert "Boss_Tentacle_Master" in tool.STAGGER_NOTES
    # the mined value is untouched — the note is about the fight, not the data
    assert _by_id()["Boss_Tentacle_Master"]["stats"]["stagger_points"]["value"] == 200.0

    text = PAGE.read_text()
    row = next(ln for ln in text.splitlines() if ln.startswith("| Tentacle Master |"))
    assert "| n/a |" in row, f"Tentacle Master still shows a stagger number: {row}"
    assert "tentacles are destroyed" in text, "the explanation for n/a is missing"
    assert "`n/a` means" in text, "n/a is used on the page but not defined in the legend"
