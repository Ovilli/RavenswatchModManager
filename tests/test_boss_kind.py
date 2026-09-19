"""The `[[content]] kind="boss"` builder: make a boss arena fight another boss.

Guardrails run without the corpus. The emit tests need the vanilla enemy
definitions and skip without them; the arena test re-asserts the corpus fact
the whole kind rests on — a swappable boss's arena selects it by FLAG, and
nothing but its own definition names its entity.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine import enemy_pools as EP
from rsmm.engine import rsc_cache as RC
from rsmm.engine.cooked_schemas import definitions as _defs
from rsmm.engine.paths import DATA_DIR
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import bosses

_MOD = "TestBossMod"


def _emit(tmp_path: Path, **fields) -> list[Path]:
    return bosses.emit(_MOD, ContentDef(kind="boss", id="swap", fields=fields), tmp_path)


def _require_corpus():
    if not EP.enemy_index():
        pytest.skip("vanilla enemy corpus not present")


# --- guardrails (corpus-free) ----------------------------------------------


@pytest.mark.parametrize("fields", [{}, {"base": "Boss_Crab"}, {"becomes": "Boss_Crab"}])
def test_base_and_becomes_are_required(tmp_path, fields):
    with pytest.raises(ContentError, match="needs '(base|becomes)'"):
        _emit(tmp_path, **fields)


def test_old_speculative_fields_are_rejected(tmp_path):
    with pytest.raises(ContentError, match="unknown field"):
        _emit(tmp_path, base="Boss_Crab", becomes="Boss_Wolf", phases=[])


@pytest.mark.parametrize("base", sorted(bosses.REFUSED))
def test_scripted_bosses_are_refused_with_a_reason(tmp_path, base):
    with pytest.raises(ContentError, match="cannot be swapped"):
        _emit(tmp_path, base=base, becomes="Boss_Crab")


def test_non_boss_base_is_refused(tmp_path):
    with pytest.raises(ContentError, match="not a swappable boss"):
        _emit(tmp_path, base="Baba_Yaga_Boss", becomes="Boss_Crab")


def test_swap_to_self_is_refused(tmp_path):
    with pytest.raises(ContentError, match="same boss"):
        _emit(tmp_path, base="Boss_Crab", becomes="Boss_Crab")


# --- emit (corpus) -----------------------------------------------------------


def _entity_of(path: Path) -> str:
    spec = _defs._SPECS["oCDtEnemyDefinition"]
    return spec.decode_body(cooked.parse(path.read_bytes()).sections[-1].payload)["entity_ref"][1]


def test_swap_repoints_the_entity_and_preloads_the_donor(tmp_path):
    _require_corpus()
    paths = _emit(tmp_path, base="Boss_Marsh_Ghoul", becomes="Boss_Crab")
    gens = [p for p in paths if p.name.endswith(".gen")]
    caches = [p for p in paths if p.name.endswith(".UsedRscCache.ot")]
    assert [p.name.split(".", 1)[0] for p in gens] == ["Boss_Marsh_Ghoul"]
    assert _entity_of(gens[0]) == "Enemies\\Crabs\\Boss_Crab.entity.ot"
    # The arena loads the ghoul's definition, so the ghoul's cache must now
    # carry the crab's closure — its own lines are kept too (append-only).
    lines = set(RC.parse(caches[0].read_bytes()))
    assert "EntitySettings|Enemies\\Crabs\\Boss_Crab.entity.ot|oCEntitySettingsResource" in lines
    own = EP.corpus_read(RC.cache_path_for(EP.cooked_rel_for("Boss_Marsh_Ghoul")))
    assert set(RC.parse(own)) <= lines
    assert RC.parse(caches[0].read_bytes()) == sorted(lines)


def test_becomes_must_be_a_boss(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="must be a boss definition"):
        _emit(tmp_path, base="Boss_Crab", becomes="Gnoll_Shielded")


def test_every_swappable_and_refused_boss_exists():
    _require_corpus()
    have = set(bosses._boss_defs())
    assert set(bosses.SWAPPABLE) | set(bosses.REFUSED) <= have


_UNCOOKED = DATA_DIR / "uncooked"


@pytest.mark.slow
def test_swappable_arenas_select_by_flag_only():
    """The fact the kind rests on: for every SWAPPABLE boss, the per-boss flag
    is referenced outside the enemy definitions (the arena), and the boss's
    entity is referenced by nothing but its own definition — except the wolf
    den, which also names its boss directly and is kept for that reason alone:
    the flag still selects it."""
    if not (_UNCOOKED / "Ot").is_dir():
        pytest.skip("uncooked corpus mirror not present")
    _require_corpus()
    spec = _defs._SPECS["oCDtEnemyDefinition"]
    files = [p for root in ("Ot", "Definitions", "EntitySettings")
             for p in (_UNCOOKED / root).rglob("*")
             if p.is_file() and "UsedRscCache" not in p.name
             and "Definitions/Enemies" not in p.as_posix()
             and p.suffix in (".gen",)]
    blobs = [p.read_bytes() for p in files]

    def refs(token: str) -> int:
        rx = re.compile(rb"(?<![A-Za-z0-9_])" + re.escape(token.encode()) + rb"(?![A-Za-z0-9_])")
        return sum(1 for b in blobs if rx.search(b))

    for boss in bosses.SWAPPABLE:
        raw = EP.corpus_read(EP.cooked_rel_for(boss))
        body = spec.decode_body(cooked.parse(raw).sections[-1].payload)
        own = [f for f in body["flags"] if f != "Boss"]
        assert own and any(refs(f) for f in own), f"{boss}: no arena references its flag"
        entity = body["entity_ref"][1].split("\\")[-1]
        if boss != "Boss_Wolf":
            assert refs(entity) == 0, f"{boss}: something besides its def names {entity}"
