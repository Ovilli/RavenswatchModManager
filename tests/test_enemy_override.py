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
    """Invariant 1, checked where `cross_biome` actually breaks it.

    A def is reached through the ENTITY it owns, so the pool that must stream
    its donor is the pool that entity was dealt to — not the biome the def
    shipped in. Those diverge the moment `cross_biome` deals across pools, and
    the assignment used to key on the shipped biome: 40 of 57 pool entries
    resolved to a prefab their own biome never streamed.

    The engine leaves a null in that pool's preload vector and the teardown
    loop at 0x140476f60 destroys it unchecked -- an access violation at
    0x1401273b6 pointing nowhere near this code (dumps 06721fec / bf959d79,
    both entering chapter 2 with chapter 1 perfectly healthy).

    Making the pools disjoint made this WORSE, not better (24 of 57 -> 40 of
    57): once no entity is in two pools, a donor in another pool is guaranteed
    not to be streamed here. So the two invariants have to be asserted
    together -- fixing either one alone is what produced both bugs.
    """
    from rsmm.engine import enemy_pools as EP
    from rsmm.sdk.kinds import enemies as E

    _require_corpus()
    owner = {r["entity"].lower(): eid
             for eid, r in EP.enemy_index().items() if r["entity"]}

    groups = E._pool_groups("t", None, None, None)
    for seed in (1337, 1, 99999):
        casts = E._biome_casts("t", groups, None, seed, True)
        assign = E._assignment("t", groups, casts, None, "shuffle", seed, True)

        placed: dict[str, list[str]] = {}
        for biome, ents in casts.items():
            for e in ents:
                placed.setdefault(e.lower(), []).append(biome)
        assert not [e for e, bs in placed.items() if len(bs) > 1], (
            f"seed {seed}: the pools stopped partitioning"
        )

        for biome, ents in casts.items():
            have = {e.lower() for e in ents}
            for e in ents:
                eid = owner.get(e.lower())
                if eid is None or eid not in assign:
                    continue
                assert assign[eid].lower() in have, (
                    f"seed {seed}: {biome} streams {e} -> def {eid} resolves to "
                    f"{assign[eid]}, which {biome} does not stream"
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
