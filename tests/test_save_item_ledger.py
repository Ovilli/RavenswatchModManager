"""Item records the game drops while an item is out of the catalog come back.

Synthetic profiles only (see test_save_editor): RSMM_GAME_DIR / RSMM_DATA_DIR
point at temp dirs, never a real `_Save`.
"""

from __future__ import annotations

import pytest
from test_save_editor import G1, G2, _full

from rsmm.engine import profile_data as PD
from rsmm.engine import save_item_ledger as L
from rsmm.engine import savefile as SF
from rsmm.engine.paths import COOKING_REL


@pytest.fixture
def game(tmp_path, monkeypatch):
    g = tmp_path / "game"
    (g / COOKING_REL).mkdir(parents=True)
    (g / "_Save").mkdir()
    monkeypatch.setenv("RSMM_GAME_DIR", str(g))
    monkeypatch.setenv("RSMM_DATA_DIR", str(tmp_path / "data"))
    (g / "_Save" / "Profile_1.ob").write_bytes(_full())
    return g


def _items(p) -> dict[bytes, SF.ItemRecord]:
    return {r.guid: r for r in SF.item_records(SF.load(p))}


def _lose(p, guid: bytes) -> None:
    """What a session without `guid` in the catalog leaves: no record for it.
    (Re-keyed in place rather than cut out: the save has no remove primitive,
    and for the ledger a record under another GUID is the same as none.)"""
    s = SF.load(p)
    at = bytes(s.data).find(guid)
    s.data[at:at + 16] = bytes(16)
    SF.write(s, backup=False)
    assert guid not in _items(p)


def test_append_keeps_every_other_byte_and_still_decodes(tmp_path):
    p = tmp_path / "Profile_1.ob"
    p.write_bytes(_full())
    s = SF.load(p)
    before, old = PD.parse(s), bytes(s.data)
    new = bytes(range(100, 116))
    SF.append_item_records(s, [new + bytes(12)])
    SF.write(s, backup=False)
    after = PD.parse(SF.load(p))
    assert len(after.objects) == len(before.objects) + 1
    assert after.root_refs == [*before.root_refs, len(before.objects)]
    assert after.objects[-1].cls == SF.ITEM_CLASS and new in _items(p)
    assert all(old[a.start:a.end] == bytes(after.save.data[b.start:b.end])
               for a, b in zip(before.objects, after.objects, strict=False))
    assert old[before.player.start:before.run.end] == \
        bytes(after.save.data[after.player.start:after.run.end])


def test_a_dropped_record_comes_back_with_its_progress(game):
    save = game / "_Save" / "Profile_1.ob"
    had = _items(save)[G1]
    assert L.sync(game) == 0                   # apply with the ban: remembered
    _lose(save, G1)                            # the banned session's save
    assert L.sync(game) == 1                   # restore: put back
    back = _items(save)[G1]
    assert SF.item_body(back) == SF.item_body(had)
    assert G2 in _items(save)
    PD.parse(SF.load(save))
    assert L.sync(game) == 0                   # nothing left to do


def test_the_temp_profile_is_repaired_too(game):
    save, temp = game / "_Save" / "Profile_1.ob", game / "_Save" / "Profile_1_Temp.ob"
    temp.write_bytes(save.read_bytes())
    L.sync(game)
    _lose(save, G1)
    _lose(temp, G1)
    assert L.sync(game) == 2
    assert G1 in _items(save) and G1 in _items(temp)


def test_dry_run_writes_nothing(game):
    save = game / "_Save" / "Profile_1.ob"
    L.sync(game)
    _lose(save, G1)
    before = save.read_bytes()
    assert L.sync(game, dry_run=True) == 1
    assert save.read_bytes() == before


def test_an_unreadable_save_is_left_alone(game):
    save = game / "_Save" / "Profile_1.ob"
    save.write_bytes(b"not a save at all, but long enough")
    assert L.sync(game) == 0
    assert save.read_bytes() == b"not a save at all, but long enough"
