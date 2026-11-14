"""Talent bans (engine/talent_bans.py, talent kind mode = "ban", the
talent-catalog config provider): a banned talent's controller stops starting
active, so it never registers into an offer pool."""

from __future__ import annotations

import pytest

from rsmm.engine import talent_bans as TB


def _corpus() -> bool:
    try:
        from rsmm.engine import corpus
        return corpus.read(TB.main_file("Hero_Red")) is not None
    except Exception:  # noqa: BLE001
        return False


needs_corpus = pytest.mark.skipif(not _corpus(), reason="no hero corpus")


@needs_corpus
def test_the_catalog_is_every_offerable_named_talent():
    cat = TB.catalog()
    red = {t.controller: t for t in cat if t.folder == "Hero_Red"}
    assert red["Skill Controller Basic Cleave"].name == "Cleave"
    assert red["Skill Controller Basic Cleave"].hero == "Scarlet"
    assert red["Skill Controller Basic Cleave"].id == "Red/Basic Cleave"
    assert sum(t.pool == 0 for t in red.values()) == 4          # the starting pick
    # not dealt: ultimates (pool 2), their upgrades (pool 3), cut talents
    assert not any("Ultimate" in c for c in red)
    assert "Skill Controller Basic Crit Chance With Combo Points" not in red  # cut
    assert len({t.id for t in cat}) == len(cat)                  # ids are unique


@needs_corpus
def test_a_ban_clears_starts_active_on_exactly_the_banned_talents():
    from rsmm.engine import entity_graph as EG
    out = TB.ban(["Red/Basic Cleave"])
    assert list(out) == [TB.main_file("Hero_Red")]
    flags = {c.name: c.flags for c in EG.parse(out[TB.main_file("Hero_Red")]).components}
    assert flags["Skill Controller Basic Cleave"] & TB.STARTS_ACTIVE == 0
    assert flags["Skill Controller Basic Cleave"] & TB.ENABLED      # still a card
    assert flags["Skill Controller Dash Attack"] & TB.STARTS_ACTIVE  # untouched


@needs_corpus
def test_a_ban_never_empties_a_pool_or_takes_unknown_ids():
    starters = [t.id for t in TB.catalog() if t.folder == "Hero_Red" and t.pool == 0]
    with pytest.raises(TB.TalentBanError, match="starting pick"):
        TB.ban(starters)
    TB.ban(starters[:-1])                                           # one left is fine
    with pytest.raises(TB.TalentBanError, match="not a bannable talent"):
        TB.ban(["Red/Ultimate Power 1"])
    with pytest.raises(TB.TalentBanError, match="<Hero>/<controller>"):
        TB.ban(["Cleave"])


def test_the_picker_provider_is_allowlisted():
    from rsmm.sdk.config_choices import PROVIDERS
    assert "talent-catalog" in PROVIDERS
