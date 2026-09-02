"""`[[content]] kind="enemy"` with ``mode="override"`` — repoint retail
populations, either onto one fixed prefab or randomised against themselves.

The two things these tests exist to hold are the two that fail silently
in-game (see the mode's commentary in ``rsmm.sdk.kinds.enemies``):

* a swap must stay inside one biome's entity pool, or the definition resolves
  to a prefab that biome never streamed;
* a swapped definition must carry a ``*.UsedRscCache.ot`` covering the new
  prefab's preload closure, sorted, or the resource resolves to null and the
  engine's teardown loop destroys it unchecked.

Runs against the real vanilla enemy corpus (skipped if absent).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsmm.engine import cooked
from rsmm.engine import enemy_pools as EP
from rsmm.engine import rsc_cache as RC
from rsmm.engine.cooked_schemas import definitions as _defs
from rsmm.engine.paths import DATA_DIR
from rsmm.sdk.content import ContentDef, ContentError
from rsmm.sdk.kinds import enemies

_UNCOOKED = DATA_DIR / "uncooked"
_TREANT = "Enemies\\Treant\\Standard_Clawed_Treant.entity.ot"


def _require_corpus():
    if not EP.enemy_index():
        pytest.skip("vanilla enemy corpus not present")


def _emit(tmp_path: Path, *, id: str = "Roster", **fields) -> list[Path]:
    defn = ContentDef(kind="enemy", id=id, fields={"mode": "override", **fields})
    return enemies.emit("TestEnemyOverrideMod", defn, tmp_path)


def _entity_of(path: Path) -> str:
    spec = _defs._SPECS["oCDtEnemyDefinition"]
    body = spec.decode_body(cooked.parse(path.read_bytes()).sections[-1].payload)
    return body["entity_ref"][1]


def _weight_of(path: Path) -> float:
    spec = _defs._SPECS["oCDtEnemyDefinition"]
    body = spec.decode_body(cooked.parse(path.read_bytes()).sections[-1].payload)
    return body["spawn_weight"]


def _gens(paths: list[Path]) -> dict[str, Path]:
    return {p.name.split(".", 1)[0]: p for p in paths if p.name.endswith(".gen")}


def _caches(paths: list[Path]) -> dict[str, Path]:
    return {p.name.split(".", 1)[0]: p
            for p in paths if p.name.endswith(RC.CACHE_SUFFIX)}


# --------------------------------------------------------------------------- #
# scope
# --------------------------------------------------------------------------- #

def test_emits_at_retail_decoded_paths(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, pools=["Dark_Hills"], entity=_TREANT)
    for enemy_id, p in _gens(written).items():
        assert p == tmp_path / Path(*EP.cooked_rel_for(enemy_id).split("/"))


def test_scope_defaults_to_open_world_pools(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, mix="shuffle", seed=1)
    index = EP.enemy_index()
    biomes = {index[e]["biome"] for e in _gens(written)}
    assert biomes and not (biomes & EP.BOSS_ARENA_POOLS)


def test_scope_never_covers_unpooled_definitions(tmp_path):
    """Bosses, summons and quest enemies are placed by the script that owns
    their encounter, so a swap there breaks a fight rather than varying the
    population. No pool streams them, which is how they are recognised."""
    _require_corpus()
    written = _emit(tmp_path, mix="random", seed=1)
    index = EP.enemy_index()
    assert all(index[e]["biome"] is not None for e in _gens(written))
    assert "Boss_Crab" not in _gens(written)


def test_exclude_drops_named_enemies(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, pools=["Storm_Island"], mix="random", seed=1,
                    exclude=["Roc_Egg", "Phoenix_Egg"])
    assert "Roc_Egg" not in _gens(written)
    assert "Phoenix_Egg" not in _gens(written)
    assert "Gnoll_Hunter" in _gens(written)


def test_unknown_pool_is_rejected(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="unknown pool"):
        _emit(tmp_path, pools=["Atlantis"], mix="random", seed=1)


def test_unknown_field_is_rejected(tmp_path):
    """Every override field is a silent no-op when misspelled — the emit
    succeeds and the run plays like vanilla."""
    _require_corpus()
    with pytest.raises(ContentError, match="unknown field"):
        _emit(tmp_path, mix="random", seed=1, poools=["Avalon"])


# --------------------------------------------------------------------------- #
# invariant 1 — a swap never leaves its biome pool
# --------------------------------------------------------------------------- #

def test_every_assigned_entity_stays_in_its_own_pool(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, mix="random", seed=99)
    index = EP.enemy_index()
    by_entity = EP.pool_of_entity()
    for enemy_id, p in _gens(written).items():
        assert by_entity[_entity_of(p).lower()] == index[enemy_id]["biome"]


def test_fixed_entity_outside_the_scope_pool_is_refused(tmp_path):
    """A treant is streamed for Dark Hills only, so it cannot be handed to
    Storm Island's roster."""
    _require_corpus()
    with pytest.raises(ContentError, match="pooled for Dark_Hills"):
        _emit(tmp_path, pools=["Storm_Island"], entity=_TREANT)


def test_unpooled_entity_is_refused(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="not in any biome spawn pool"):
        _emit(tmp_path, pools=["Avalon"],
              entity="Enemies\\Crabs\\Boss_Crab.entity.ot")


# --------------------------------------------------------------------------- #
# invariant 2 — the resource cache travels with the swap
# --------------------------------------------------------------------------- #

def test_repointed_definition_gets_a_merged_sorted_cache(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, pools=["Dark_Hills"], entity=_TREANT)
    donor = set(RC.parse(
        (_UNCOOKED / "Definitions" / "Enemies"
         / f"Standard_Clawed_Treant.enemydef{RC.CACHE_SUFFIX}").read_bytes()))

    caches = _caches(written)
    assert caches, "a repointed def with no cache preloads the wrong closure"
    for enemy_id, p in caches.items():
        lines = RC.parse(p.read_bytes())
        # Sorted is load-bearing: the engine looks a resource up in here
        # rather than scanning, so a line past the end is never reached.
        assert lines == sorted(lines)
        own = set(RC.parse(
            (_UNCOOKED / "Definitions" / "Enemies"
             / f"{enemy_id}.enemydef{RC.CACHE_SUFFIX}").read_bytes()))
        # Union, never replacement — a surplus line wastes a preload of a real
        # shipped file, a missing one crashes the game.
        assert own <= set(lines)
        assert donor <= set(lines)
        assert any(_TREANT in ln for ln in lines)


def test_cache_lands_beside_the_definition(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, pools=["Dark_Hills"], entity=_TREANT)
    for enemy_id, p in _caches(written).items():
        want = RC.cache_path_for(EP.cooked_rel_for(enemy_id))
        assert p == tmp_path / Path(*want.split("/"))


# --------------------------------------------------------------------------- #
# codec + payload
# --------------------------------------------------------------------------- #

def test_byte_identical_override_emits_nothing(tmp_path):
    """Re-encoding is byte-stable, so the definition that already owned the
    target prefab comes out identical to the shipped file. Installing it would
    back a file up and replace it with itself, leaving the restore path
    carrying a backup for a change that was never made.

    This doubles as the byte-stability check: the file is dropped *because*
    the re-encode reproduced the retail bytes exactly, which is the guarantee
    every other untouched field in the scope rests on."""
    _require_corpus()
    written = _emit(tmp_path, pools=["Dark_Hills"], entity=_TREANT)
    assert "Standard_Clawed_Treant" not in _gens(written)
    assert _gens(written), "the rest of the pool should still be rewritten"


def test_weight_only_edit_still_emits(tmp_path):
    """Dropping unchanged files must key on the bytes, not on the entity — a
    def that keeps its prefab but gets a new weight is a real edit."""
    _require_corpus()
    written = _emit(tmp_path, pools=["Dark_Hills"], entity=_TREANT, weight=7.0)
    assert _weight_of(_gens(written)["Standard_Clawed_Treant"]) == 7.0
    # The prefab it already pointed at is covered by the cache it already
    # ships, so there is nothing to merge in.
    assert "Standard_Clawed_Treant" not in _caches(written)


def test_fixed_entity_repoints_the_whole_pool(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, pools=["Dark_Hills"], entity=_TREANT)
    assert {_entity_of(p) for p in _gens(written).values()} == {_TREANT}


def test_uniform_weight_is_applied(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, pools=["Avalon"], mix="shuffle", seed=3, weight=5.0)
    assert {_weight_of(p) for p in _gens(written).values()} == {5.0}


def test_weight_ceiling_is_enforced(tmp_path):
    """9999 overflowed the weighted camp-roster selection and crashed the
    game (enemy-spawn-model)."""
    _require_corpus()
    with pytest.raises(ContentError, match="exceeds the safe ceiling"):
        _emit(tmp_path, pools=["Avalon"], mix="random", seed=1, weight=9999)


# --------------------------------------------------------------------------- #
# randomisation
# --------------------------------------------------------------------------- #

def test_same_seed_emits_identical_bytes(tmp_path):
    """The roll is baked into the assets at apply time, so the seed is the
    only thing co-op peers have to agree on."""
    _require_corpus()
    a, b = tmp_path / "a", tmp_path / "b"
    wa, wb = _emit(a, mix="random", seed=42), _emit(b, mix="random", seed=42)
    assert sorted(p.relative_to(a) for p in wa) == sorted(p.relative_to(b) for p in wb)
    for p in wa:
        assert p.read_bytes() == (b / p.relative_to(a)).read_bytes()


def test_different_seed_rolls_differently(tmp_path):
    _require_corpus()
    one = {k: _entity_of(v) for k, v in _gens(_emit(tmp_path / "1",
                                                    mix="random", seed=1)).items()}
    two = {k: _entity_of(v) for k, v in _gens(_emit(tmp_path / "2",
                                                    mix="random", seed=2)).items()}
    assert one != two


def test_seed_is_scoped_per_biome(tmp_path):
    """Adding a pool to the scope must not reshuffle the pools already in it,
    or tuning one biome silently rerolls the rest."""
    _require_corpus()
    narrow = {k: _entity_of(v) for k, v in _gens(
        _emit(tmp_path / "n", pools=["Avalon"], mix="random", seed=5)).items()}
    wide = {k: _entity_of(v) for k, v in _gens(
        _emit(tmp_path / "w", pools=["Avalon", "Dark_Hills"],
              mix="random", seed=5)).items()}
    assert narrow == {k: v for k, v in wide.items() if k in narrow}


def test_shuffle_is_a_permutation_of_each_pool(tmp_path):
    """Unlike "random", a shuffle preserves the biome's composition — every
    creature still appears exactly once, only the labels move."""
    _require_corpus()
    written = _emit(tmp_path, mix="shuffle", seed=11)
    index = EP.enemy_index()
    got: dict[str, list[str]] = {}
    want: dict[str, list[str]] = {}
    for enemy_id, p in _gens(written).items():
        biome = index[enemy_id]["biome"]
        got.setdefault(biome, []).append(_entity_of(p))
        want.setdefault(biome, []).append(index[enemy_id]["entity"])
    assert {b: sorted(v) for b, v in got.items()} == {b: sorted(v) for b, v in want.items()}


def test_shuffle_never_leaves_a_pool_untouched(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, mix="shuffle", seed=11)
    index = EP.enemy_index()
    moved: dict[str, bool] = {}
    for enemy_id, p in _gens(written).items():
        biome = index[enemy_id]["biome"]
        moved[biome] = moved.get(biome, False) or (
            _entity_of(p) != index[enemy_id]["entity"])
    assert all(moved.values())


# --------------------------------------------------------------------------- #
# mode plumbing
# --------------------------------------------------------------------------- #

def test_mix_and_entity_are_mutually_exclusive(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="mutually exclusive"):
        _emit(tmp_path, pools=["Dark_Hills"], entity=_TREANT, mix="random", seed=1)


def test_mix_requires_a_seed(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="integer 'seed'"):
        _emit(tmp_path, pools=["Avalon"], mix="random")


def test_override_needs_an_edit(tmp_path):
    _require_corpus()
    with pytest.raises(ContentError, match="needs either"):
        _emit(tmp_path, pools=["Avalon"])


def test_unknown_mode_is_rejected(tmp_path):
    defn = ContentDef(kind="enemy", id="X", fields={"mode": "wobble"})
    with pytest.raises(ContentError, match="unknown mode"):
        enemies.emit("TestEnemyOverrideMod", defn, tmp_path)


def test_clone_mode_is_unchanged(tmp_path):
    """The default path must keep working exactly as before the mode switch."""
    _require_corpus()
    defn = ContentDef(kind="enemy", id="Dreadgnoll",
                      fields={"base": "Gnoll_Shielded", "weight": 4.0})
    (out,) = enemies.emit("TestEnemyOverrideMod", defn, tmp_path)
    assert out.name.startswith("Dreadgnoll.")
    assert _weight_of(out) == 4.0


def test_cross_biome_casts_keep_the_pools_disjoint():
    """The shipped EntityPooling assets partition — no entity is in two of
    them. `cross_biome` must not break that.

    It did: an independent draw per biome from the same 50-creature set put 12
    of 39 entities into two-to-four pools at once. A shared entity is a shared
    lifetime, and every chapter after the first tears the previous biome's pool
    down while building its own, so a creature both of them list can be freed
    out from under the incoming preload vector — a black screen entering
    chapter 2 with chapter 1 perfectly healthy.
    """
    from rsmm.engine import enemy_pools as EP
    from rsmm.sdk.kinds import enemies as E

    _require_corpus()
    vanilla = {b: [e.lower() for e in ents] for b, ents in EP.pools().items()
               if b not in EP.BOSS_ARENA_POOLS}
    seen: dict[str, list[str]] = {}
    for biome, ents in vanilla.items():
        for e in ents:
            seen.setdefault(e, []).append(biome)
    assert not [e for e, bs in seen.items() if len(bs) > 1], (
        "the shipped pools no longer partition — the premise of this test "
        "changed, not the code under it"
    )

    groups = E._pool_groups("t", None, None, None)
    for seed in (1337, 1, 99999):
        casts = E._biome_casts("t", groups, None, seed, True)
        placed: dict[str, list[str]] = {}
        for biome, ents in casts.items():
            for e in ents:
                placed.setdefault(e.lower(), []).append(biome)
        dupes = {e: bs for e, bs in placed.items() if len(bs) > 1}
        assert not dupes, f"seed {seed}: entities in >1 pool: {dupes}"


def test_cross_biome_defs_resolve_inside_their_own_pool():
    """Invariant 1: every def in scope gets a donor its own biome streams.

    A def is rolled by a camp because of its TRIBE, and a `cross_biome` run
    moves neither tribes nor camps — so a def still spawns in the biome it is
    keyed under, and its donor has to come from that biome's repointed cast.

    Asserted for a SCOPED run as well as a full one, because that is where it
    broke. For one day the assignment was re-keyed by where each cast entity
    had been dealt (690df15); with `pools = ["Dark_Hills"]` — whose cast is
    drawn from every biome — that emitted 7 of the 15 Dark Hills defs plus 8
    out-of-scope ones. The 8 missing defs kept pointing at vanilla entities
    the repointed pool no longer streams, so they could not spawn and the
    population looked untouched.
    """
    from rsmm.sdk.kinds import enemies as E

    _require_corpus()
    scopes = [None, ["Dark_Hills"]]
    for pools in scopes:
        groups = E._pool_groups("t", pools, None, None)
        for seed in (1337, 1, 99999):
            casts = E._biome_casts("t", groups, None, seed, True)
            assign = E._assignment("t", groups, casts, None, "shuffle", seed)

            in_scope = {eid for ids in groups.values() for eid in ids}
            assert set(assign) == in_scope, (
                f"scope {pools}, seed {seed}: assignment covers "
                f"{len(assign)} def(s), scope has {len(in_scope)}"
            )
            for biome, ids in groups.items():
                have = {e.lower() for e in casts[biome]}
                for eid in ids:
                    assert assign[eid].lower() in have, (
                        f"scope {pools}, seed {seed}: {biome} def {eid} "
                        f"resolves to {assign[eid]}, which {biome} does not "
                        f"stream"
                    )


def test_bounded_imports_preserve_the_partition_and_the_native_majority():
    """`imports = N` must move creatures between biomes WITHOUT putting any
    creature in two pools.

    The partition is what the disjoint-pool work bought, and the obvious
    implementation loses it: picking a foreigner from the global set can pick a
    creature the biome that owns it is also keeping, so one entity lands in two
    pools. Bounded imports are therefore SWAPS, which are partition-preserving
    by construction.

    Also asserts the point of the knob — that most slots keep the creature they
    shipped with. A bound that quietly replaced the whole cast would look
    identical to a full deal and test nothing.
    """
    from rsmm.engine import enemy_pools as EP
    from rsmm.sdk.kinds import enemies as E

    _require_corpus()
    groups = E._pool_groups("t", None, None, None)
    native = {b: {e.lower() for e in ents}
              for b, ents in E._biome_casts("t", groups, None, 1337, False).items()}

    for seed in (1337, 1, 99999):
        for n in (1, 3):
            casts = E._biome_casts("t", groups, None, seed, True, n)

            placed: dict[str, list[str]] = {}
            for biome, ents in casts.items():
                for e in ents:
                    placed.setdefault(e.lower(), []).append(biome)
            assert not [e for e, bs in placed.items() if len(bs) > 1], (
                f"imports={n} seed={seed} put a creature in two pools"
            )

            # Sizes are untouched: the oCGameStream vector cannot grow.
            for biome, ents in casts.items():
                assert len(ents) == len(native[biome]), (
                    f"{biome} changed size under imports={n}"
                )

            # And the cast is still mostly its own.
            for biome, ents in casts.items():
                foreign = [e for e in ents if e.lower() not in native[biome]]
                assert len(foreign) < len(ents), (
                    f"{biome} kept nothing of its own at imports={n}"
                )

    # More imports means more foreigners — otherwise the knob does nothing.
    def _foreign_total(n):
        casts = E._biome_casts("t", groups, None, 1337, True, n)
        return sum(len([e for e in ents if e.lower() not in native[b]])
                   for b, ents in casts.items())

    assert _foreign_total(1) < _foreign_total(6), (
        "raising imports did not import more"
    )


def test_scoped_cross_biome_is_refused():
    """`cross_biome` narrower than every open-world pool must not plant.

    The cast is dealt from every spawnable creature, but only the pools in
    scope are rewritten — so a creature dealt in from another biome is listed
    by two pools at once (measured: 8 of 15 with pools = ["Dark_Hills"], seed
    1337). That is the shared-lifetime shape the partition work removed, and
    it is what a scoped run silently re-creates.
    """
    from rsmm.sdk.kinds import enemies as E

    _require_corpus()
    defn = ContentDef(kind="enemy", id="scoped",
                      fields={"mode": "override", "pools": ["Dark_Hills"],
                              "cross_biome": True, "seed": 1337,
                              "mix": "shuffle"})
    with pytest.raises(ContentError, match="every biome's pool"):
        E.emit("TestEnemyOverrideMod", defn, Path("/nonexistent"))


def test_repoint_pools_false_touches_no_pool_asset(tmp_path):
    """`repoint_pools = false` must emit definitions and NOT a single level.

    The pool repoint is this kind's only edit to an `EntityPooling` level, and
    the only failure mode anyone has seen is a chapter transition. This
    configuration keeps the game-wide cast and drops the level edit, so the
    transition path stays byte-identical to vanilla. The imported prefab is
    still preloaded, by the merged per-definition resource cache.
    """
    from rsmm.sdk.kinds import enemies as E

    _require_corpus()
    defn = ContentDef(kind="enemy", id="nopool",
                      fields={"mode": "override", "cross_biome": True,
                              "repoint_pools": False, "seed": 1337,
                              "mix": "shuffle"})
    written = E.emit("TestEnemyOverrideMod", defn, tmp_path)
    assert written, "nothing emitted"
    pools = [p for p in written if "EntityPooling" in p.name]
    assert not pools, f"repoint_pools = false still wrote {pools}"

    # And the imported prefab IS preloaded: every emitted cache lists the
    # entity its definition now points at.
    from rsmm.engine import enemy_pools as EP
    from rsmm.engine import rsc_cache as RC

    groups = E._pool_groups(defn.id, None, None, None)
    casts = E._biome_casts(defn.id, groups, None, 1337, True, None)
    assignment = E._assignment(defn.id, groups, casts, None, "shuffle", 1337)
    caches = {p.name: p for p in written if p.name.endswith(".UsedRscCache.ot")}
    checked = 0
    for eid, ent in assignment.items():
        if ent.lower() == EP.enemy_index()[eid]["entity"].lower():
            continue
        cache = caches.get(f"{eid}.enemydef.UsedRscCache.ot")
        assert cache is not None, f"{eid} repointed with no cache emitted"
        lines = {ln.lower() for ln in RC.parse(cache.read_bytes())}
        assert any(ent.lower() in ln for ln in lines), \
            f"{eid}: merged cache does not preload {ent}"
        checked += 1
    assert checked >= 10, f"only {checked} repointed defs checked"


def test_repoint_pools_false_allows_a_scoped_cross_biome():
    """Scoping is refused only because a rewritten pool leaves entities shared.

    With no pool rewritten there is no partition to break, so the refusal must
    not fire — otherwise the safe configuration inherits the unsafe one's rule.
    """
    from rsmm.sdk.kinds import enemies as E

    _require_corpus()
    defn = ContentDef(kind="enemy", id="scoped_nopool",
                      fields={"mode": "override", "pools": ["Dark_Hills"],
                              "cross_biome": True, "repoint_pools": False,
                              "seed": 1337, "mix": "shuffle"})
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        assert E.emit("TestEnemyOverrideMod", defn, Path(d))


def test_repoint_pools_false_without_cross_biome_is_refused():
    from rsmm.sdk.kinds import enemies as E

    _require_corpus()
    defn = ContentDef(kind="enemy", id="pointless",
                      fields={"mode": "override", "repoint_pools": False,
                              "seed": 1337, "mix": "shuffle"})
    with pytest.raises(ContentError, match="cross_biome = true"):
        E.emit("TestEnemyOverrideMod", defn, Path("/nonexistent"))


# --------------------------------------------------------------------------- #
# `casts` — a hand-written cast per chapter instead of a dealt one.
# --------------------------------------------------------------------------- #


def _cast_fields(**over):
    fields = {"mode": "override", "cross_biome": True, "repoint_pools": False,
              "mix": "random", "seed": 7}
    fields.update(over)
    return fields


def test_cast_pins_a_chapter_to_the_monsters_it_names(tmp_path):
    """The whole point: a chapter spawns only what the author cast in it.

    Dark Hills is pinned to two Storm Island creatures, so every Dark Hills
    definition must end up pointing at one of exactly those two — and no
    other chapter may move because of it.
    """
    _require_corpus()
    crab = "Enemies\\Crabs\\Standard_Reef_Crab.entity.ot"
    jinn = "Standard_Storm_Jinn"
    written = _emit(tmp_path, id="pinned",
                    **_cast_fields(casts={"Dark_Hills": [crab, jinn]}))
    want = {enemies._creature_entity("pinned", n).lower() for n in (crab, jinn)}

    groups = enemies._pool_groups("pinned", None, None, None)
    gens = _gens(written)
    seen = set()
    for eid in groups["Dark_Hills"]:
        got = _entity_of(gens[eid]).lower()
        assert got in want, f"{eid} points at {got}, not one of the cast"
        seen.add(got)
    assert seen == want, "a cast monster never got used"

    # Another chapter still holds its dealt cast, not the pinned one.
    other = {_entity_of(gens[e]).lower() for e in groups["Avalon"] if e in gens}
    assert not (other & want), "pinning one chapter leaked into another"


def test_cast_of_one_makes_the_whole_chapter_that_monster(tmp_path):
    _require_corpus()
    written = _emit(tmp_path, id="allcrab",
                    **_cast_fields(casts={"Dark_Hills": ["Standard_Reef_Crab"]}))
    groups = enemies._pool_groups("allcrab", None, None, None)
    gens = _gens(written)
    ents = {_entity_of(gens[e]).lower() for e in groups["Dark_Hills"]}
    assert len(ents) == 1, f"expected one monster, got {ents}"


def test_cast_accepts_id_stem_and_full_ref(tmp_path):
    _require_corpus()
    ref = "Enemies\\Crabs\\Standard_Reef_Crab.entity.ot"
    assert (enemies._creature_entity("x", "Standard_Reef_Crab")
            == enemies._creature_entity("x", ref)
            == enemies._creature_entity("x", ref.replace("\\", "/")))


def test_cast_rejects_a_creature_no_camp_rolls():
    _require_corpus()
    with pytest.raises(ContentError, match="camp-spawnable"):
        _emit(Path("/nonexistent"), id="boss",
              **_cast_fields(casts={"Dark_Hills": ["Baba_Yaga"]}))


def test_cast_rejects_an_unknown_chapter():
    _require_corpus()
    with pytest.raises(ContentError, match="unknown chapter"):
        _emit(Path("/nonexistent"), id="nochapter",
              **_cast_fields(casts={"Mordor": ["Standard_Reef_Crab"]}))


def test_cast_outside_the_scope_is_refused():
    """Otherwise the cast is built and no definition is ever assigned from it."""
    _require_corpus()
    with pytest.raises(ContentError, match="leaves alone"):
        _emit(Path("/nonexistent"), id="outofscope",
              **_cast_fields(pools=["Avalon"],
                             casts={"Dark_Hills": ["Standard_Reef_Crab"]}))


def test_foreign_cast_without_cross_biome_is_refused():
    """A chapter cannot stream a prefab nothing brings into it."""
    _require_corpus()
    with pytest.raises(ContentError, match="cross_biome = true"):
        _emit(Path("/nonexistent"), id="foreign",
              **_cast_fields(cross_biome=False, repoint_pools=True,
                             casts={"Dark_Hills": ["Standard_Reef_Crab"]}))


def test_cast_shared_between_chapters_is_refused_when_pools_are_rewritten():
    """The partition is what stops a chapter transition freeing a live entity."""
    _require_corpus()
    crab = "Standard_Reef_Crab"
    with pytest.raises(ContentError, match="cast in both"):
        _emit(Path("/nonexistent"), id="shared",
              **_cast_fields(repoint_pools=True,
                             casts={"Dark_Hills": [crab], "Avalon": [crab]}))


def test_cast_longer_than_the_pool_is_refused_when_pools_are_rewritten():
    _require_corpus()
    from rsmm.engine import enemy_pools as EP

    slots = len(enemies._def_owned_slots("Dark_Hills"))
    too_many = EP.spawnable_entities()[: slots + 1]
    with pytest.raises(ContentError, match="pool slots"):
        _emit(Path("/nonexistent"), id="toolong",
              **_cast_fields(repoint_pools=True, casts={"Dark_Hills": too_many}))


def test_cast_and_fixed_entity_are_mutually_exclusive():
    _require_corpus()
    with pytest.raises(ContentError, match="mutually exclusive"):
        _emit(Path("/nonexistent"), id="both",
              **_cast_fields(mix=None, seed=None, entity=_TREANT,
                             casts={"Dark_Hills": ["Standard_Reef_Crab"]}))


def test_same_cast_emits_identical_bytes(tmp_path):
    """Order and duplicates in the manifest must not change the install."""
    _require_corpus()
    a = _emit(tmp_path / "a", id="det",
              **_cast_fields(casts={"Dark_Hills": ["Standard_Reef_Crab",
                                                   "Standard_Storm_Jinn"]}))
    b = _emit(tmp_path / "b", id="det",
              **_cast_fields(casts={"Dark_Hills": ["Standard_Storm_Jinn",
                                                   "Standard_Reef_Crab",
                                                   "Standard_Reef_Crab"]}))
    assert [p.name for p in a] == [p.name for p in b]
    for pa, pb in zip(a, b, strict=True):
        assert pa.read_bytes() == pb.read_bytes(), pa.name


def test_config_picker_supplies_a_chapter_cast(tmp_path):
    """The desktop config panel is the player-facing way to write a cast.

    A `multiselect` field named after a chapter IS that chapter's cast, so the
    picked monsters must reach the emitted definitions exactly as a manifest
    `casts` entry would.
    """
    _require_corpus()
    mod = tmp_path / "mod"
    (mod / "assets").mkdir(parents=True)
    (mod / "config_schema.toml").write_text(
        '[fields.Dark_Hills]\ntype = "multiselect"\nsource = "enemy-roster"\n'
        'default = []\n[fields.Avalon]\ntype = "multiselect"\n'
        'source = "enemy-roster"\ndefault = []\n', encoding="utf-8")
    (mod / "config.toml").write_text(
        '[config]\nDark_Hills = ["Standard_Reef_Crab"]\nAvalon = []\n',
        encoding="utf-8")

    defn = ContentDef(kind="enemy", id="picked",
                      fields={"mode": "override", "cross_biome": True,
                              "repoint_pools": False, "mix": "random",
                              "seed": 7})
    written = enemies.emit("TestEnemyOverrideMod", defn, mod / "assets")
    groups = enemies._pool_groups("picked", None, None, None)
    gens = _gens(written)
    dark = {_entity_of(gens[e]).lower() for e in groups["Dark_Hills"]}
    assert dark == {"enemies\\crabs\\standard_reef_crab.entity.ot"}
    # An empty pick is "not configured", so that chapter keeps its roll.
    avalon = {_entity_of(gens[e]).lower() for e in groups["Avalon"] if e in gens}
    assert len(avalon) > 1, "empty picker should leave the chapter rolled"


def test_config_picker_beats_the_manifest_cast(tmp_path):
    _require_corpus()
    mod = tmp_path / "mod"
    (mod / "assets").mkdir(parents=True)
    (mod / "config_schema.toml").write_text(
        '[fields.Dark_Hills]\ntype = "multiselect"\nsource = "enemy-roster"\n'
        'default = []\n', encoding="utf-8")
    (mod / "config.toml").write_text(
        '[config]\nDark_Hills = ["Standard_Reef_Crab"]\n', encoding="utf-8")

    defn = ContentDef(kind="enemy", id="beats",
                      fields={"mode": "override", "cross_biome": True,
                              "repoint_pools": False, "mix": "random",
                              "seed": 7,
                              "casts": {"Dark_Hills": ["Standard_Clawed_Treant"]}})
    written = enemies.emit("TestEnemyOverrideMod", defn, mod / "assets")
    groups = enemies._pool_groups("beats", None, None, None)
    gens = _gens(written)
    dark = {_entity_of(gens[e]).lower() for e in groups["Dark_Hills"]}
    assert dark == {"enemies\\crabs\\standard_reef_crab.entity.ot"}


def test_enemy_roster_provider_offers_only_spawnable_creatures():
    _require_corpus()
    from rsmm.engine import enemy_pools as EP
    from rsmm.sdk.config_choices import provide

    opts = provide("enemy-roster")
    assert len(opts) == len(EP.spawnable_entities())
    ids = {o["id"] for o in opts}
    assert len(ids) == len(opts), "prefab stems must be unique ids"
    for oid in ids:
        # Every offered id must be one the kind accepts, or the picker would
        # hand `apply` a choice it then refuses.
        enemies._creature_entity("provider", oid)
    assert {o["group"] for o in opts} >= {"Dark Hills", "Avalon", "Storm Island"}
