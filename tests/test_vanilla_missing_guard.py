"""Guard against the 2026-07-11 text-bank data loss.

Chain that destroyed vanilla assets:

  1. A game update wiped `.rsmm_state.json` AND the `.rsmm.bak` files, and
     replaced/removed some cooked files.
  2. The next `rsmm apply` found no vanilla file under a mod's text-bank
     override, so it recorded the override with `orig_sha256=""` — the
     encoding for "this file was ADDED by a mod".
  3. `rsmm disable` then dropped every added file, deleting vanilla
     `Text/Tutorials~GAM` (base + 13 langs) and `Hero_Aladdin_Common`
     (13 langs). The engine renders "Default sentence" for every string when
     a bank is missing.

`apply_one` now refuses step 2. These tests pin both the refusal and the
carve-out for genuinely new assets, which must still apply.
"""

from __future__ import annotations

import pytest

from rsmm.cli import apply_mods as AM
from rsmm.engine.asset_map import decoded_to_encoded, encoded_to_decoded

_BANK = "Text/Tutorials~GAM.xls.LocalText.gen"


@pytest.fixture()
def state(tmp_path):
    return AM.State(tmp_path)


def _apply(enc, tmp_path, state, **kw):
    src = tmp_path / "src.bin"
    src.write_bytes(b"override")
    dest = tmp_path / "cooking" / "missing.bin"      # deliberately absent
    return AM.apply_one(enc, src, dest, "SomeMod", state, dry_run=False, **kw)


# --- what counts as vanilla ------------------------------------------------

def test_base_text_bank_is_recognised_as_vanilla():
    enc = decoded_to_encoded()[_BANK]
    assert AM.is_vanilla_encoded(enc)


def test_every_lang_sibling_is_recognised_as_vanilla():
    """The subtle half. Lang siblings are NOT in asset_map (it is derived from
    UsedRscList.ot, which lists only the base), so an `enc in asset_map` check
    would have caught 1 of the 14 files lost per bank and missed the other 13."""
    d2e = decoded_to_encoded()
    missed = []
    for lang in AM.LANG_DECODED_TO_ENCODED:
        decoded = f"{_BANK}.Lang{lang}"
        enc = d2e.get(decoded) or AM.resolve_special(decoded, d2e)
        assert enc, decoded
        assert enc not in encoded_to_decoded(), "premise: siblings aren't mapped"
        if not AM.is_vanilla_encoded(enc):
            missed.append(decoded)
    assert not missed, f"lang siblings not recognised as vanilla: {missed}"


def test_a_genuinely_new_asset_is_not_vanilla():
    assert not AM.is_vanilla_encoded("Nqhdzdidrzv\\Mzqxdqv\\TotallyMadeUp.yqz")
    assert not AM.is_vanilla_encoded("Qqpi\\NoSuchBank.yqz.GgzyMU")


def _enc(decoded: str) -> str:
    from rsmm.engine.cipher import encode

    return encode(decoded.replace("/", "\\"))


def test_shipped_resource_caches_are_recognised_as_vanilla():
    """The same shape as the lang-sibling loss, for a second family.

    A `*.UsedRscCache.ot` is loaded by CONVENTION — the engine appends the
    suffix to the resource name — so none of the 575 shipped caches has a
    UsedRscList record and none is in asset_map. `enc in asset_map` therefore
    answers False for every one of them, and the drop path would delete a game
    file. This is not hypothetical: the `poi` kind overrides shipped caches on
    every apply (a tiledef whose cache is missing is never placed, and one
    whose cache is stale crashes the game at level build).
    """
    shipped = "Definitions/Tiles/Dark_Hills/40x40_Dark_Hills_Start_Update3.tiledef.UsedRscCache.ot"
    enc = _enc(shipped)
    assert enc not in encoded_to_decoded(), "premise: caches are not in asset_map"
    assert AM.is_vanilla_encoded(enc)

    # A cache belonging to a tile the MOD introduced has no vanilla owner, so
    # it must stay droppable — otherwise restore leaves the mod's files behind.
    mod_cache = "Definitions/Tiles/Dark_Hills/mymod_new_tile.tiledef.UsedRscCache.ot"
    assert not AM.is_vanilla_encoded(_enc(mod_cache))


def test_shipped_sound_banks_are_recognised_as_vanilla():
    """The other family outside asset_map: the engine opens `Audio/<Name>.bank`
    by path, so the 16 shipped banks never appear in the manifest either."""
    enc = _enc("Audio/Music.bank")
    assert enc not in encoded_to_decoded(), "premise: banks are not in asset_map"
    assert AM.is_vanilla_encoded(enc)


# --- the refusal -----------------------------------------------------------

def test_apply_refuses_when_the_vanilla_original_is_missing(tmp_path, state):
    enc = decoded_to_encoded()[_BANK]
    with pytest.raises(AM.VanillaMissing, match="refusing to apply"):
        _apply(enc, tmp_path, state)


def test_refusal_records_no_state_entry(tmp_path, state):
    """The whole point: no entry means nothing to later drop as 'added'."""
    enc = decoded_to_encoded()[_BANK]
    with pytest.raises(AM.VanillaMissing):
        _apply(enc, tmp_path, state)
    assert enc not in state.active


def test_refusal_message_names_the_recovery_path(tmp_path, state):
    enc = decoded_to_encoded()[_BANK]
    with pytest.raises(AM.VanillaMissing) as e:
        _apply(enc, tmp_path, state)
    assert "Verify integrity" in str(e.value)


def test_lang_sibling_is_refused_too(tmp_path, state):
    d2e = decoded_to_encoded()
    decoded = f"{_BANK}.LangDE"
    enc = d2e.get(decoded) or AM.resolve_special(decoded, d2e)
    with pytest.raises(AM.VanillaMissing):
        _apply(enc, tmp_path, state)


def test_force_overrides_the_refusal(tmp_path, state):
    enc = decoded_to_encoded()[_BANK]
    _apply(enc, tmp_path, state, force=True)
    assert state.active[enc]["orig_sha256"] == ""


# --- the carve-out ---------------------------------------------------------

def test_new_assets_still_apply_as_added(tmp_path, state):
    """Custom items/enemies/textures have no vanilla original by design and
    must keep applying — and must keep being dropped on restore."""
    enc = "Nqhdzdidrzv\\Mzqxdqv\\BrandNewThing.yqz"
    _apply(enc, tmp_path, state)
    assert state.active[enc]["orig_sha256"] == ""


# --- restore side: the guard that actually holds --------------------------
#
# The apply-side refusal is NOT sufficient on its own. `restore_one` drops any
# file with no backup and no recorded original, and that branch fires even
# when there is no state entry at all — so a vanilla file could still be
# deleted with the apply guard in place. Both guards are load-bearing.

def _incident(tmp_path, enc, *, force):
    """Replay the full chain and report whether the vanilla file survives.

    update wipes vanilla -> apply -> Steam verify restores vanilla -> disable
    """
    cooking = tmp_path / "cooking"
    cooking.mkdir()
    src = tmp_path / "src.bin"
    src.write_bytes(b"override")
    dest = AM.encoded_to_dest(enc, cooking, tmp_path)
    st = AM.State(cooking)

    blocked = False
    try:
        AM.apply_one(enc, src, dest, "M", st, dry_run=False, force=force)
    except AM.VanillaMissing:
        blocked = True

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"VANILLA-TEXT-BANK")          # Steam verify
    AM.restore_one(enc, cooking, st_dir_state(st), st, dry_run=False)
    return blocked, dest.exists() and dest.read_bytes() == b"VANILLA-TEXT-BANK"


def st_dir_state(state):
    """restore_one takes (cooking, game_dir); both derive from the state path."""
    return state.path.parent.parent


def test_vanilla_survives_the_full_incident_chain(tmp_path):
    enc = decoded_to_encoded()[_BANK]
    blocked, survived = _incident(tmp_path, enc, force=False)
    assert blocked
    assert survived, "vanilla text bank was deleted by disable"


def test_vanilla_survives_even_a_forced_apply(tmp_path):
    """--force skips the apply guard, so only the restore guard stands. It
    must be enough on its own — this is the case a stale/wiped state hits."""
    enc = decoded_to_encoded()[_BANK]
    blocked, survived = _incident(tmp_path, enc, force=True)
    assert not blocked
    assert survived, "restore-side guard did not hold"


def test_restore_still_drops_a_genuinely_added_file(tmp_path):
    """The guard must not turn restore into a no-op for real mod assets."""
    cooking = tmp_path / "cooking"
    cooking.mkdir()
    enc = "Nqhdzdidrzv\\Mzqxdqv\\BrandNewThing.yqz"
    dest = AM.encoded_to_dest(enc, cooking, tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"mod asset")
    st = AM.State(cooking)
    st.active[enc] = {"mod": "M", "src_sha256": "x", "orig_sha256": ""}

    assert AM.restore_one(enc, cooking, tmp_path, st, dry_run=False)
    assert not dest.exists(), "added file should still be removed"
    assert enc not in st.active


def test_existing_file_is_backed_up_not_refused(tmp_path, state):
    """The normal path is untouched: a present vanilla file gets a .bak and a
    real orig_sha256, so restore puts it back rather than deleting it."""
    enc = decoded_to_encoded()[_BANK]
    src = tmp_path / "src.bin"
    src.write_bytes(b"override")
    dest = tmp_path / "cooking" / "there.bin"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"vanilla")

    AM.apply_one(enc, src, dest, "SomeMod", state, dry_run=False)

    bak = dest.parent / (dest.name + AM.BACKUP_SUFFIX)
    assert bak.read_bytes() == b"vanilla"
    assert dest.read_bytes() == b"override"
    assert state.active[enc]["orig_sha256"], "must not look like an added file"
