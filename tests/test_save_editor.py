"""The Save tab and the record layers under it, on synthetic profiles.

Nothing here reads or writes a real `_Save`: every profile is built in a temp
install pointed at by RSMM_GAME_DIR, and backups go to RSMM_DATA_DIR.
"""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import savefile as SF
from rsmm.engine.paths import COOKING_REL

OPEN, CLOSE = struct.pack("<I", SF.MARKER_OPEN), struct.pack("<I", SF.MARKER_CLOSE)
G1, G2 = bytes(range(16)), bytes(range(16, 32))


def _profile(items: list[tuple[bytes, tuple[int, int, int, int, int]]], *,
             table_extra: int = 0) -> bytes:
    """A profile in the real layout: root record + one 40-byte record per item."""
    classes = [("oCDtGameProfile", 12), (SF.ITEM_CLASS, 5)]
    reg = b"".join(struct.pack("<I", len(n)) + n.encode()
                   + struct.pack("<IIII", 0x1000 + i, 1, v, 0)
                   for i, (n, v) in enumerate(classes))
    table = [0] + [1] * (len(items) + table_extra)
    data = CLOSE + OPEN + struct.pack(f"<I{len(table)}I", len(table), *table) + CLOSE
    data += OPEN + struct.pack("<I", 0) + b"root" + CLOSE
    for guid, (a, b, c, num, e) in items:
        body = struct.pack("<16sIBBBiB", guid, 0, a, b, c, num, e)
        data += OPEN + struct.pack("<I", 1) + body + CLOSE
    body = struct.pack("<II", SF.MAGIC, len(classes)) + reg + data
    import zlib
    return struct.pack("<IIII", 0x10, 0, 1, zlib.crc32(body) & 0xFFFFFFFF) + body


def _write(tmp_path, raw: bytes, name: str = "Profile_1.ob"):
    p = tmp_path / name
    p.write_bytes(raw)
    return SF.load(p)


def test_item_records_read_every_record(tmp_path):
    s = _write(tmp_path, _profile([(G1, (1, 1, 0, 3, 0)), (G2, (1, 0, 1, -1, 0))]))
    recs = SF.item_records(s)
    assert [(r.guid, r.state()) for r in recs] == [(G1, "granted"), (G2, "other")]
    assert s.crc_ok


def test_a_state_edit_changes_only_its_record_and_resigns(tmp_path):
    s = _write(tmp_path, _profile([(G1, (1, 1, 0, 3, 0)), (G2, (1, 0, 1, -1, 0))]))
    before = bytes(s.data)
    rec = SF.item_records(s)[1]
    SF.set_item_state(s, rec, "reset")
    changed = [i for i in range(len(before)) if before[i] != s.data[i]]
    assert changed and all(rec.offset <= i < rec.offset + 40 for i in changed)
    SF.resign(s)
    again = SF.load(SF.write(s, backup=False))
    assert again.crc_ok
    assert [r.state() for r in SF.item_records(again)] == ["granted", "reset"]


def test_granted_leaves_the_fields_the_game_leaves(tmp_path):
    s = _write(tmp_path, _profile([(G1, (0, 0, 1, -1, 1))]))
    new = SF.set_item_state(s, SF.item_records(s)[0], "granted")
    assert (new.f60, new.f61, new.f62, new.f64, new.f68) == (1, 1, 1, 3, 1)


def test_a_walk_that_disagrees_with_the_object_table_is_refused(tmp_path):
    s = _write(tmp_path, _profile([(G1, (1, 1, 0, 3, 0))], table_extra=1))
    with pytest.raises(SF.SaveFormatError, match="object table"):
        SF.item_records(s)


# --- every record (engine.profile_data) ----------------------------------------------
from rsmm.engine import profile_data as PD  # noqa: E402

H, SK, SN = bytes([0xA0] * 16), bytes([0xB0] * 16), bytes([0xC0] * 16)
_CLASSES = [("oCDtGameProfile", 12), (SF.ITEM_CLASS, 5), ("oCDtHeroProfileData", 18),
            ("SkillProfileData", 5), ("oCGameLockPersistentData", 1), ("oCGameEventListener", 1),
            ("oCDtPlayerProfileData", 8), ("oCDtCurrentRunProfileData", 19),
            ("SkinProfileData", 0), ("HeroRankGameLockConditionData", 0)]
_IX = {n: i for i, (n, _v) in enumerate(_CLASSES)}


def _o(cls: str, body: bytes = b"") -> bytes:
    return OPEN + struct.pack("<I", _IX[cls]) + body + CLOSE


def _lock(unlocked: int, new: int, refs: tuple[int, ...] = ()) -> bytes:
    listener = _o("oCGameEventListener", struct.pack("<Iffi", 0, 0.0, 3.4e38, -1))
    body = struct.pack("<BBI", unlocked, new, len(refs)) + struct.pack(f"<{len(refs)}I", *refs)
    return _o("oCGameLockPersistentData", body + listener)


def _full(*, versions: dict[str, int] | None = None) -> bytes:
    """A whole profile in the real layout: two items, a hero, a talent and an
    outfit (each with its lock), an unlock condition, then the profile record
    with the player record and a suspended run."""
    classes = [(n, (versions or {}).get(n, v)) for n, v in _CLASSES]
    reg = b"".join(struct.pack("<I", len(n)) + n.encode()
                   + struct.pack("<IIII", 0x1000 + i, 1, v, 0) for i, (n, v) in enumerate(classes))
    objs = [
        _o(SF.ITEM_CLASS, struct.pack("<16sIBBBiB", G1, 0, 1, 1, 0, 3, 0)),
        _o(SF.ITEM_CLASS, struct.pack("<16sIBBBiB", G2, 0, 1, 0, 1, -1, 0)),
        _o("oCDtHeroProfileData", H + struct.pack("<IfIIIiBIIi", 0, 2.5, 9, 1, 4, 3, 1, 2, 0, 11)
           + _lock(1, 0)),
        _o("SkillProfileData", SK + struct.pack("<Ii", 0, -1) + _lock(0, 0, (5,))),
        _o("SkinProfileData", SN + struct.pack("<I", 0) + _lock(0, 0, (5,))),
        _o("HeroRankGameLockConditionData"),
    ]
    table = [SF.ITEM_CLASS, SF.ITEM_CLASS, "oCDtHeroProfileData", "SkillProfileData",
             "SkinProfileData", "HeroRankGameLockConditionData"]
    ids = [_IX[c] for c in table]
    data = CLOSE + OPEN + struct.pack(f"<I{len(ids)}I", len(ids), *ids) + CLOSE + b"".join(objs)
    root = (struct.pack("<I5I", 5, 0, 1, 2, 3, 4)
            + _o("oCDtPlayerProfileData", struct.pack("<iiiBI", 3, 0, 12, 1, 0))
            + _o("oCDtCurrentRunProfileData", b"a suspended run"))
    data += _o("oCDtGameProfile", root)
    body = struct.pack("<II", SF.MAGIC, len(classes)) + reg + data
    import zlib
    return struct.pack("<IIII", 0x10, 0, 1, zlib.crc32(body) & 0xFFFFFFFF) + body


def test_every_record_decodes_to_its_end(tmp_path):
    p = PD.parse(_write(tmp_path, _full()))
    assert [n.cls for n in p.objects] == ["oCDtMagicalObjectProfileData"] * 2 + [
        "oCDtHeroProfileData", "SkillProfileData", "SkinProfileData",
        "HeroRankGameLockConditionData"]
    hero = p.objects[2]
    assert hero.get("level") == 2.5 and PD.lock_state(hero.children["lock"]) == "unlocked"
    assert p.objects[3].children["lock"].get("conditions") == [5]
    assert p.player.get("value10") == 12 and p.run.end > p.run.start


def test_edits_change_only_their_bytes_and_still_decode(tmp_path):
    s = _write(tmp_path, _full())
    p = PD.parse(s)
    before = bytes(s.data)
    PD.set_lock(s, p.objects[4].children["lock"], "unlocked")
    PD.set_talent_tier(s, p.objects[3], 3)
    PD.set_hero_level(s, p.objects[2], 8.0)
    PD.set_item_state(s, p.objects[1], "granted")
    assert len(s.data) == len(before)
    SF.resign(s)
    again = PD.parse(SF.load(SF.write(s, backup=False)))
    assert PD.lock_state(again.objects[4].children["lock"]) == "unlocked"
    assert again.objects[4].children["lock"].get("new") == 1      # as the game's own unlock
    assert again.objects[3].get("tier") == 3 and again.objects[2].get("level") == 8.0
    assert PD.item_state(again.objects[1]) == "granted"


@pytest.mark.parametrize("call", [
    lambda s, p: PD.set_hero_level(s, p.objects[2], 9.0),
    lambda s, p: PD.set_talent_tier(s, p.objects[3], 4),
    lambda s, p: PD.set_talent_tier(s, p.objects[2], 1),          # not a talent
    lambda s, p: PD.set_lock(s, p.objects[2].children["lock"], "open"),
])
def test_out_of_range_edits_are_refused(tmp_path, call):
    s = _write(tmp_path, _full())
    before = bytes(s.data)
    with pytest.raises((ValueError, KeyError)):
        call(s, PD.parse(s))
    assert bytes(s.data) == before


def test_a_class_at_another_schema_version_is_not_read(tmp_path):
    s = _write(tmp_path, _full(versions={"oCDtHeroProfileData": 19}))
    with pytest.raises(SF.SaveFormatError, match="v19"):
        PD.parse(s)


# --- the Save tab ------------------------------------------------------------------
@pytest.fixture
def install(tmp_path, monkeypatch):
    game = tmp_path / "game"
    (game / COOKING_REL).mkdir(parents=True)
    (game / "_Save").mkdir()
    monkeypatch.setenv("RSMM_GAME_DIR", str(game))
    monkeypatch.setenv("RSMM_DATA_DIR", str(tmp_path / "data"))
    from rsmm.cli.editor import content, saves
    monkeypatch.setattr(saves, "_names", lambda prof: {
        G1.hex(): {"name": "One", "id": "Item_One", "group": ""},
        G2.hex(): {"name": "Two", "id": "Item_Two", "group": ""},
        H.hex(): {"name": "Aladdin", "id": "Aladdin", "group": "Aladdin"},
        SK.hex(): {"name": "Attack Dive", "id": "", "group": "Aladdin"},
        SN.hex(): {"name": "Raven Outfit", "id": "", "group": "Aladdin"}})
    monkeypatch.setattr(content, "items", lambda: [
        {"id": "Item_One", "name": "One", "rarity": "Common", "icon": None},
        {"id": "Item_Two", "name": "Two", "rarity": "Rare", "icon": None}])
    monkeypatch.setattr("rsmm.engine.game_proc.is_game_running", lambda: False)
    raw = _full()
    (game / "_Save" / "Profile_1.ob").write_bytes(raw)
    (game / "_Save" / "Profile_1_Temp.ob").write_bytes(raw)
    return game / "_Save", raw


def _req(body=None, **query):
    from rsmm.cli.editor.app import Context, Request
    return Request(Context(), "POST" if body is not None else "GET", "/", query, body or {})


def _change(oid, guid, field, value):
    return {"id": oid, "guid": guid.hex(), "field": field, "value": value}


def test_the_tab_shows_every_kind(install):
    from rsmm.cli.editor import saves
    assert [p["name"] for p in saves._profiles(_req())["profiles"]] == ["Profile_1.ob"]
    j = saves._read(_req(profile="Profile_1.ob"))
    rows = {s["key"]: s["rows"] for s in j["sections"]}
    assert [(r["name"], r["item"]) for r in rows["items"]] == [("One", "granted"), ("Two", "other")]
    assert rows["heroes"][0]["level"] == 2.5 and rows["heroes"][0]["lock"] == "unlocked"
    assert (rows["talents"][0]["tier"], rows["talents"][0]["lock"]) == (-1, "locked")
    assert rows["skins"][0]["name"] == "Raven Outfit"
    assert j["player"]["value08"] == 3


def test_writing_backs_up_both_files_and_keeps_them_identical(install, tmp_path):
    from rsmm.cli.editor import saves
    save_dir, raw = install
    j = saves._write(_req({"profile": "Profile_1.ob", "changes": [
        _change(1, G2, "item", "granted"), _change(4, SN, "lock", "unlocked"),
        _change(2, H, "level", 8), _change(3, SK, "tier", 3)]}))
    main = (save_dir / "Profile_1.ob").read_bytes()
    temp = (save_dir / "Profile_1_Temp.ob").read_bytes()
    assert main == temp != raw and len(main) == len(raw)
    p = PD.parse(SF.load(save_dir / "Profile_1.ob"))
    assert PD.item_state(p.objects[1]) == "granted" and p.objects[2].get("level") == 8.0
    assert PD.lock_state(p.objects[4].children["lock"]) == "unlocked"
    assert p.objects[3].get("tier") == 3
    backup = tmp_path / "data" / "save_backups" / j["backup"]
    assert (backup / "Profile_1.ob").read_bytes() == raw
    assert (backup / "Profile_1_Temp.ob").read_bytes() == raw


def test_nothing_is_written_while_the_game_runs(install, monkeypatch):
    from rsmm.cli.editor import saves
    from rsmm.cli.editor.app import Fail
    save_dir, raw = install
    monkeypatch.setattr("rsmm.engine.game_proc.is_game_running", lambda: True)
    with pytest.raises(Fail, match="running"):
        body = {"profile": "Profile_1.ob", "changes": [_change(1, G2, "item", "granted")]}
        saves._write(_req(body))
    assert (save_dir / "Profile_1.ob").read_bytes() == raw


@pytest.mark.parametrize("body", [
    {"profile": "../Profile_1.ob", "changes": [_change(1, G2, "item", "granted")]},
    {"profile": "Profile_1.ob", "changes": [_change(1, G2, "item", "max")]},
    {"profile": "Profile_1.ob", "changes": [_change(1, G1, "item", "granted")]},   # wrong GUID
    {"profile": "Profile_1.ob", "changes": [_change(2, H, "level", 99)]},
    {"profile": "Profile_1.ob", "changes": [_change(2, H, "count30", 5)]},          # read-only
    {"profile": "Profile_1.ob", "changes": [_change(3, SK, "tier", True)]},
    {"profile": "Profile_1.ob", "changes": [_change(1, G2, "item", "granted"),
                                            _change(9, G2, "item", "granted")]},  # no such record
])
def test_a_bad_write_is_refused_and_writes_nothing(install, body):
    from rsmm.cli.editor import saves
    from rsmm.cli.editor.app import Fail
    save_dir, raw = install
    with pytest.raises((Fail, ValueError)):
        saves._write(_req(body))
    assert (save_dir / "Profile_1.ob").read_bytes() == raw
    assert not (saves._backup_root()).exists()


def test_putting_a_backup_back_backs_up_the_current_file_first(install):
    from rsmm.cli.editor import saves
    save_dir, raw = install
    body = {"profile": "Profile_1.ob", "changes": [_change(1, G2, "item", "reset")]}
    first = saves._write(_req(body))["backup"]
    edited = (save_dir / "Profile_1.ob").read_bytes()
    j = saves._restore(_req({"backup": first}))
    assert (save_dir / "Profile_1.ob").read_bytes() == raw
    undo = saves._backup_root() / j["undo"][0] / "Profile_1.ob"
    assert undo.read_bytes() == edited
