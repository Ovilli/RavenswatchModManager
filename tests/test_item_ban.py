"""Item ban (``kind="item"`` / ``mode="ban"``) — catalog removal.

The ban drops entries from the LiveOps versiondef magical-object vector so the
engine never pools them and no draw can offer them. It is the only
multiplayer-correct lever for disabling an item: the offer roll is seeded and
host-authoritative deterministic, so a per-peer runtime filter desyncs the run
(``docs/_re/kinds/rewards.md``), while identical assets on every peer keep the
deterministic draw identical everywhere.

These tests build a synthetic versiondef blob rather than reading the install,
so they run without a game or a corpus.
"""

from __future__ import annotations

import json
import struct

import pytest

from rsmm.cli import apply_mods as A


def _entry(path: str) -> bytes:
    t = b"EntitySettings"
    pb = path.encode("latin1")
    return (struct.pack("<I", len(t)) + t
            + struct.pack("<I", len(pb)) + pb)


def _versiondef(ids: list[str], *, prefix: bytes = b"HEAD", suffix: bytes = b"TAIL") -> bytes:
    """A blob whose only plausible MO vector is the one we build."""
    body = b"".join(
        _entry(f"Objects\\Magical_Objects\\Common\\{i}.entity.ot") for i in ids
    )
    return prefix + struct.pack("<I", len(ids)) + body + suffix


IDS = [f"Item_{n:02d}" for n in range(25)]


def _stems(blob: bytes) -> list[str]:
    co, _end, cnt = A._find_mo_vector(blob)
    return [A._mo_entry_stem(e[2]) for e in A._mo_vector_entries(blob, co, cnt)]


# --- vector plumbing -------------------------------------------------------

def test_synthetic_vector_is_locatable():
    blob = _versiondef(IDS)
    assert _stems(blob) == IDS


def test_entry_stem_strips_directory_and_suffix():
    assert A._mo_entry_stem(
        "Objects\\Magical_Objects\\Legendary\\Balor_Eye.entity.ot"
    ) == "Balor_Eye"


# --- banning ---------------------------------------------------------------

def test_ban_removes_entry_and_decrements_count():
    blob = _versiondef(IDS)
    out = A._patch_versiondef_gen(blob, [], {"Item_07"})
    assert out is not None
    co, _end, cnt = A._find_mo_vector(out)
    assert cnt == len(IDS) - 1
    assert "Item_07" not in _stems(out)


def test_ban_keeps_every_other_entry_in_order():
    blob = _versiondef(IDS)
    out = A._patch_versiondef_gen(blob, [], {"Item_00", "Item_24"})
    assert _stems(out) == IDS[1:-1]


def test_ban_preserves_bytes_outside_the_vector():
    blob = _versiondef(IDS, prefix=b"BEFORE-BYTES", suffix=b"AFTER-BYTES")
    out = A._patch_versiondef_gen(blob, [], {"Item_03"})
    assert out.startswith(b"BEFORE-BYTES")
    assert out.endswith(b"AFTER-BYTES")


def test_ban_is_case_insensitive():
    blob = _versiondef(IDS)
    out = A._patch_versiondef_gen(blob, [], {"item_05"})
    assert "Item_05" not in _stems(out)


def test_unknown_ban_leaves_blob_untouched():
    blob = _versiondef(IDS)
    assert A._patch_versiondef_gen(blob, [], {"No_Such_Item"}) == blob


def test_ban_is_idempotent():
    blob = _versiondef(IDS)
    once = A._patch_versiondef_gen(blob, [], {"Item_09"})
    twice = A._patch_versiondef_gen(once, [], {"Item_09"})
    assert twice == once


def test_add_and_ban_in_one_pass_keep_count_consistent():
    """Count must match the entries actually present — the failure this
    single-rebuild path exists to make impossible."""
    blob = _versiondef(IDS)
    new = "Objects\\Magical_Objects\\Epic\\Custom_Thing.entity.ot"
    out = A._patch_versiondef_gen(blob, [new], {"Item_02", "Item_11"})
    co, _end, cnt = A._find_mo_vector(out)
    stems = _stems(out)
    assert cnt == len(stems) == len(IDS) - 2 + 1
    assert "Custom_Thing" in stems
    assert "Item_02" not in stems and "Item_11" not in stems


def test_adding_an_already_present_path_does_not_duplicate():
    blob = _versiondef(IDS)
    dup = "Objects\\Magical_Objects\\Common\\Item_04.entity.ot"
    assert A._patch_versiondef_gen(blob, [dup], set()) == blob


def test_banning_then_re_adding_the_same_item_readds_it():
    """`paths` wins over `bans` for the same item — the add is appended after
    the ban filter, so a mod that clones over a banned base still lands."""
    blob = _versiondef(IDS)
    path = "Objects\\Magical_Objects\\Common\\Item_06.entity.ot"
    out = A._patch_versiondef_gen(blob, [path], {"Item_06"})
    assert _stems(out).count("Item_06") == 1


# --- emit side -------------------------------------------------------------

def _defn(**fields):
    from rsmm.sdk.content import ContentDef
    return ContentDef(kind="item", id=fields.pop("id", "bans"), fields=fields)


def _emit(tmp_path, **fields):
    from rsmm.sdk.kinds import items
    return items.emit("testmod", _defn(**fields), tmp_path)


def test_ban_mode_writes_staging_json_and_no_asset(tmp_path):
    written = _emit(tmp_path, mode="ban", items=[_a_bannable_id()])
    assert len(written) == 1
    p = written[0]
    assert p.parent.name == "_pending_bans"
    doc = json.loads(p.read_text())
    assert doc["items"] == [_a_bannable_id()]
    # nothing outside the staging dir, so nothing gets installed
    assert {f.parent.name for f in tmp_path.rglob("*") if f.is_file()} == {"_pending_bans"}


def test_ban_accepts_a_bare_string(tmp_path):
    written = _emit(tmp_path, mode="ban", items=_a_bannable_id())
    assert json.loads(written[0].read_text())["items"] == [_a_bannable_id()]


def _known_ids() -> list[str]:
    """Ids `_emit_ban` will accept here — same preference order it uses."""
    from rsmm.sdk.kinds import items
    return sorted(items._catalog_item_ids() or items._vanilla_item_ids())


def _a_bannable_id() -> str:
    """A ban id that emit accepts in this environment.

    With neither an install nor a corpus reachable (CI: `data/uncooked` is
    gitignored) `_emit_ban` validates nothing, so any name is accepted and the
    emit-shape tests still exercise the real path.
    """
    known = _known_ids()
    return known[0] if known else "Armor_Per_Object"


def test_ban_dedupes_and_sorts(tmp_path):
    known = _known_ids()
    a, b = (known[0], known[3]) if known else ("A_Item", "B_Item")
    written = _emit(tmp_path, mode="ban", items=[b, a, b])
    assert json.loads(written[0].read_text())["items"] == sorted({a, b})


def test_empty_ban_list_is_refused(tmp_path):
    from rsmm.sdk.content import ContentError
    with pytest.raises(ContentError, match="non-empty"):
        _emit(tmp_path, mode="ban", items=[])


def test_unknown_field_is_refused(tmp_path):
    """Every ban field is a silent no-op when misspelled, so unknown keys raise
    rather than being ignored."""
    from rsmm.sdk.content import ContentError
    with pytest.raises(ContentError, match="unknown field"):
        _emit(tmp_path, mode="ban", items=["Armor_Per_Object"], itens=["oops"])


def test_unknown_mode_is_refused(tmp_path):
    from rsmm.sdk.content import ContentError
    with pytest.raises(ContentError, match="unknown mode"):
        _emit(tmp_path, mode="banish", items=[_a_bannable_id()])


def test_unknown_item_id_is_refused_when_ids_resolvable(tmp_path):
    from rsmm.sdk.content import ContentError
    if not _known_ids():
        pytest.skip("neither an install catalog nor a corpus is reachable")
    with pytest.raises(ContentError, match="no magical object named"):
        _emit(tmp_path, mode="ban", items=["Definitely_Not_An_Item"])


def test_known_item_id_is_accepted(tmp_path):
    known = _known_ids()
    if not known:
        pytest.skip("neither an install catalog nor a corpus is reachable")
    assert _emit(tmp_path, mode="ban", items=[known[0]])


def test_catalog_is_preferred_over_the_wider_corpus(tmp_path):
    """The shipped corpus lists entities the catalog never does (``*_Model``
    templates, unreleased items); banning one is a no-op, so it must be refused
    rather than accepted on the corpus's word."""
    from rsmm.sdk.content import ContentError
    from rsmm.sdk.kinds import items
    catalog = items._catalog_item_ids()
    if catalog is None:
        pytest.skip("no install reachable")
    corpus_only = sorted(items._vanilla_item_ids() - catalog)
    if not corpus_only:
        pytest.skip("this install's catalog covers the whole corpus")
    with pytest.raises(ContentError, match="install catalog"):
        _emit(tmp_path, mode="ban", items=[corpus_only[0]])


def test_ban_emits_when_nothing_is_reachable(tmp_path, monkeypatch):
    """CI has neither an install nor `data/uncooked` (gitignored). With nothing
    to check against the ban must still emit — unvalidated, not refused —
    otherwise no mod could be built on a clean checkout."""
    from rsmm.sdk.kinds import items
    monkeypatch.setattr(items, "_catalog_item_ids", lambda: None)
    monkeypatch.setattr(items, "_vanilla_item_ids", lambda: set())
    written = _emit(tmp_path, mode="ban", items=["Whatever_This_Is"])
    assert json.loads(written[0].read_text())["items"] == ["Whatever_This_Is"]


def test_corpus_is_used_when_no_install_is_reachable(tmp_path, monkeypatch):
    from rsmm.sdk.content import ContentError
    from rsmm.sdk.kinds import items
    monkeypatch.setattr(items, "_catalog_item_ids", lambda: None)
    monkeypatch.setattr(items, "_vanilla_item_ids", lambda: {"Real_Item"})
    assert _emit(tmp_path, mode="ban", items=["Real_Item"])
    with pytest.raises(ContentError, match="asset corpus"):
        _emit(tmp_path, mode="ban", items=["Fake_Item"])


# --- collection ------------------------------------------------------------

class _FakeMod:
    def __init__(self, root, mod_id, enabled=True):
        self.id = mod_id
        self.enabled = enabled
        self.assets_dir = root / mod_id / "assets"

    def stage(self, items):
        d = self.assets_dir / "_pending_bans"
        d.mkdir(parents=True, exist_ok=True)
        (d / "b.json").write_text(json.dumps({"items": items}))
        return self


def test_collect_unions_bans_across_mods(tmp_path):
    a = _FakeMod(tmp_path, "a").stage(["One"])
    b = _FakeMod(tmp_path, "b").stage(["Two"])
    assert A.collect_item_bans([a, b]) == {"One", "Two"}


def test_collect_skips_disabled_mods(tmp_path):
    a = _FakeMod(tmp_path, "a").stage(["One"])
    b = _FakeMod(tmp_path, "b", enabled=False).stage(["Two"])
    assert A.collect_item_bans([a, b]) == {"One"}


def test_collect_tolerates_a_corrupt_ban_file(tmp_path):
    a = _FakeMod(tmp_path, "a").stage(["One"])
    b = _FakeMod(tmp_path, "b")
    d = b.assets_dir / "_pending_bans"
    d.mkdir(parents=True)
    (d / "b.json").write_text("{not json")
    assert A.collect_item_bans([a, b]) == {"One"}


def test_collect_is_empty_without_staging_dirs(tmp_path):
    m = _FakeMod(tmp_path, "a")
    m.assets_dir.mkdir(parents=True)
    assert A.collect_item_bans([m]) == set()


# --- config picker contract -----------------------------------------------

def _schema(**over):
    from rsmm.sdk.config import ConfigSchema
    body = {"type": "multiselect", "source": "item-catalog", "label": "L"}
    body.update(over)
    return ConfigSchema.from_dict({"fields": {"banned": body}})


def test_multiselect_is_a_config_type():
    assert _schema().fields["banned"].type == "multiselect"


def test_unknown_option_provider_is_refused():
    from rsmm.sdk.config import ConfigError
    with pytest.raises(ConfigError, match="not a known option provider"):
        _schema(source="curl-whatever")


def test_multiselect_coerces_to_a_sorted_unique_list():
    f = _schema().fields["banned"]
    assert f.coerce(["B", "A", "B", " "]) == ["A", "B"]
    assert f.coerce("A") == ["A"]
    assert f.coerce([]) == []


def test_multiselect_rejects_a_non_list():
    from rsmm.sdk.config import ConfigError
    with pytest.raises(ConfigError, match="expected a list"):
        _schema().fields["banned"].coerce(7)


def test_provider_backed_field_keeps_ids_it_cannot_currently_see():
    """The valid set lives in the game install and can be unreadable. Rejecting
    an unknown id would DELETE the player's selection the first time the CLI
    ran where the catalog could not be read."""
    f = _schema(choices=["Known"]).fields["banned"]
    assert f.coerce(["Unknown_Thing"]) == ["Unknown_Thing"]


def test_static_choices_are_still_enforced_without_a_provider():
    from rsmm.sdk.config import ConfigError
    f = _schema(source=None, choices=["Known"]).fields["banned"]
    assert f.coerce(["Known"]) == ["Known"]
    with pytest.raises(ConfigError, match="not in"):
        f.coerce(["Nope"])


def test_list_values_round_trip_through_the_store(tmp_path):
    from rsmm.sdk.config import ConfigStore
    (tmp_path / "config_schema.toml").write_text(
        '[fields.banned]\ntype = "multiselect"\nsource = "item-catalog"\n')
    store = ConfigStore(tmp_path)
    store.set("banned", ["B", "A"])
    assert ConfigStore(tmp_path).get("banned") == ["A", "B"]


def test_choice_options_are_normalised():
    from rsmm.sdk.config_choices import _clean
    assert _clean({"id": "x"}) == {
        "id": "x", "label": "x", "group": "", "icon": "", "description": ""}
    assert _clean({}) is None
    assert _clean("nope") is None


def test_non_data_url_icons_are_dropped():
    """A path or remote URL must never reach the client, which would then fetch
    it on the mod's behalf."""
    from rsmm.sdk.config_choices import _clean
    for bad in ("https://example.invalid/x.png", "/etc/passwd", "file:///x"):
        assert _clean({"id": "x", "icon": bad})["icon"] == ""
    good = "data:image/png;base64,AAAA"
    assert _clean({"id": "x", "icon": good})["icon"] == good


def test_oversized_icon_is_dropped():
    from rsmm.sdk.config_choices import MAX_ICON_CHARS, _clean
    huge = "data:image/png;base64," + "A" * MAX_ICON_CHARS
    assert _clean({"id": "x", "icon": huge})["icon"] == ""


def test_unknown_provider_yields_no_options_rather_than_raising():
    """A config panel that opens empty beats one that will not open."""
    from rsmm.sdk.config_choices import provide
    assert provide("no-such-provider") == []


def test_managed_mod_declares_a_valid_picker(tmp_path):
    from rsmm.engine import item_bans
    from rsmm.sdk.config import ConfigStore
    item_bans.write_bans(["Armor_Per_Object"], mods_dir=tmp_path)
    store = ConfigStore(tmp_path / "banned-items")
    field = store.schema.fields[item_bans.CONFIG_FIELD]
    assert field.type == "multiselect"
    assert field.source == "item-catalog"


def test_writing_bans_seeds_the_picker_so_the_two_agree(tmp_path):
    """Without this the picker opens with nothing ticked while the manifest
    bans items, and the first save silently un-bans them."""
    from rsmm.engine import item_bans
    item_bans.write_bans(["Armor_Per_Object", "Balor"], mods_dir=tmp_path)
    assert item_bans.read_config_selection(mods_dir=tmp_path) == [
        "Armor_Per_Object", "Balor"]


def test_picker_selection_wins_over_a_stale_manifest_list(tmp_path):
    from rsmm.engine import item_bans
    from rsmm.sdk.config import ConfigStore
    item_bans.write_bans(["Armor_Per_Object"], mods_dir=tmp_path)
    ConfigStore(tmp_path / "banned-items").set("banned", ["Something_Else"])
    assert item_bans.read_bans(mods_dir=tmp_path) == ["Something_Else"]


def test_emit_uses_the_picker_selection(tmp_path, monkeypatch):
    from rsmm.engine import item_bans
    from rsmm.sdk.config import ConfigStore
    from rsmm.sdk.kinds import items
    item_bans.write_bans(["Armor_Per_Object"], mods_dir=tmp_path)
    root = tmp_path / "banned-items"
    ConfigStore(root).set("banned", ["Picked_One"])
    monkeypatch.setattr(items, "_catalog_item_ids", lambda: None)
    monkeypatch.setattr(items, "_vanilla_item_ids", lambda: set())
    written = items.emit("banned-items",
                         _defn(id="b", mode="ban", items=["Stale_Manifest_One"]),
                         root / "assets")
    assert json.loads(written[0].read_text())["items"] == ["Picked_One"]


def test_a_mod_without_a_picker_keeps_its_manifest_list(tmp_path):
    from rsmm.sdk.kinds import items
    assert items._config_selection(tmp_path) is None


# --- crash guards ----------------------------------------------------------

def _mixed(counts: dict[str, int]) -> tuple[bytes, dict[str, list[str]]]:
    """A versiondef whose entries are spread across rarity folders."""
    by: dict[str, list[str]] = {}
    body = b""
    for rarity, n in counts.items():
        by[rarity] = []
        for i in range(n):
            item = f"{rarity}_{i:02d}"
            by[rarity].append(item)
            body += _entry(f"Objects\\Magical_Objects\\{rarity}\\{item}.entity.ot")
    total = sum(counts.values())
    return b"HEAD" + struct.pack("<I", total) + body + b"TAIL", by


def test_ban_that_would_empty_a_rarity_is_refused(capsys):
    """The engine picks offers with `rand() % candidate_count`, so a pool that
    reaches zero is an INT_DIVIDE_BY_ZERO — observed opening the shop with 103
    of 104 items banned."""
    blob, by = _mixed({"Common": 10, "Rare": 10, "Legendary": 10})
    assert A._clamp_bans(blob, set(by["Common"])) == set()
    err = capsys.readouterr().err
    assert "refusing the whole ban list" in err
    assert "Common" in err


def test_banning_nearly_everything_is_refused():
    blob, by = _mixed({"Common": 10, "Rare": 10, "Legendary": 10})
    every = {i for ids in by.values() for i in ids}
    assert A._clamp_bans(blob, every - {"Rare_00"}) == set()


def test_leaving_one_item_per_rarity_is_allowed():
    """A global floor would have vetoed this; the invariant is per-rarity."""
    blob, by = _mixed({"Common": 10, "Rare": 10, "Legendary": 10})
    bans = {i for ids in by.values() for i in ids[1:]}
    assert A._clamp_bans(blob, bans) == bans


def test_a_modest_ban_is_left_alone():
    blob, by = _mixed({"Common": 10, "Rare": 10})
    keep = {by["Common"][0], by["Rare"][0]}
    assert A._clamp_bans(blob, keep) == keep


def test_clamp_ignores_ban_ids_that_match_nothing():
    blob, by = _mixed({"Common": 10, "Rare": 10})
    bans = {by["Common"][0], "Not_A_Real_Item", "Also_Fake"}
    assert A._clamp_bans(blob, bans) == bans


def test_emptying_a_mods_content_removes_its_staged_files(tmp_path):
    """Dropping the last `[[content]]` block used to orphan whatever it emitted,
    and the apply pipeline kept consuming those files forever."""
    root = tmp_path / "amod"
    staged = root / "assets" / "_pending_bans" / "b.json"
    staged.parent.mkdir(parents=True)
    staged.write_text('{"items": ["X"]}')
    (root / ".rsmm_emitted.json").write_text('["_pending_bans/b.json"]')

    class _M:
        id = "amod"
        enabled = True
        content_blocks: list = []
        assets_dir = root / "assets"
    m = _M()
    m.root = root
    A._drop_emitted(m)
    assert not staged.exists()
    assert not (root / ".rsmm_emitted.json").exists()


def test_clearing_the_picker_does_not_resurrect_the_manifest_list(tmp_path):
    """`items` is the fallback for a mod with no picker. Once a picker exists,
    an empty selection means nothing banned — falling back would silently
    re-ban whatever the manifest still listed."""
    from rsmm.engine import item_bans
    from rsmm.sdk.config import ConfigStore
    item_bans.write_bans(["Armor_Per_Object", "Balor"], mods_dir=tmp_path)
    ConfigStore(tmp_path / "banned-items").set("banned", [])
    assert item_bans.read_bans(mods_dir=tmp_path) == []


def test_a_mod_without_a_picker_still_uses_its_manifest_list(tmp_path):
    from rsmm.engine import item_bans
    root = tmp_path / "handmade"
    root.mkdir()
    (root / "manifest.toml").write_text(
        '[mod]\nid = "handmade"\n\n[[content]]\nkind = "item"\nmode = "ban"\n'
        'id = "b"\nitems = ["Armor_Per_Object"]\n')
    assert not item_bans.has_picker("handmade", tmp_path)
    assert item_bans.read_bans("handmade", tmp_path) == ["Armor_Per_Object"]
