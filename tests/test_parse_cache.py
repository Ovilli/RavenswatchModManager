"""Parse caches and the cached install-dir scan return/behave like uncached ones."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from rsmm.cli import apply_mods
from rsmm.engine import cipher, cooked, corpus, entity_graph, paths, rsc_cache

_OTHER = "[Comp] Scope"+chr(92)+"Group"+chr(92)+"Other"


def _lstr(s: str) -> bytes:
    b = s.encode("ascii")
    return struct.pack("<I", len(b)) + b


def _picker(cls: int, guid: bytes, path: str) -> bytes:
    return cooked.MARK_BEGIN + struct.pack("<I", cls) + guid + _lstr(path) + cooked.MARK_END


def _entity_bytes() -> bytes:
    classes = [cooked.ClassDef("oCEntityCpntPicker", 1, 0, 0, 0),
               cooked.ClassDef("oCThing", 2, 0, 0, 0)]
    own = bytes(range(16))
    target = bytes(range(16, 32))
    comp = (struct.pack("<I", 1) + _picker(0, bytes(16), "") + own
            + _lstr("Name") + struct.pack("<I", 0) + _lstr("Group")
            + _picker(0, target, _OTHER) + _lstr("lit_string"))
    secs = [cooked.Section(b"head"), cooked.Section(comp), cooked.Section(b"tail")]
    cf = cooked.CookedFile("A", 0x10, 1, 1, cooked.DEFAULT_TYPE_TAG, classes, secs)
    return cooked.emit(cf)


def test_cooked_parse_returns_independent_objects():
    raw = _entity_bytes()
    a = cooked.parse(raw)
    a.sections.append(cooked.Section(b"x"))
    a.sections[0].payload = b"changed"
    a.classes[0].name = "mutated"
    a.classes.pop()
    a.flags = 99
    b = cooked.parse(raw)
    assert cooked.emit(b) == raw
    assert b.classes[0].name == "oCEntityCpntPicker" and len(b.classes) == 2
    assert b is not a and b.sections is not a.sections


def test_cooked_parse_non_bytes_matches_bytes():
    raw = _entity_bytes()
    assert cooked.parse(bytearray(raw)) == cooked.parse(raw)


def test_cooked_parse_error_not_cached():
    for _ in range(2):
        with pytest.raises(ValueError):
            cooked.parse(b"\x10\x00\x00\x00\x00\x00\x00\x00junk")


def test_entity_graph_parse_returns_independent_objects():
    raw = _entity_bytes()
    g = entity_graph.parse(raw, "E")
    assert len(g.components) == 1
    c = g.components[0]
    assert c.refs and c.literals
    c.refs[0].path = "mutated"
    c.refs.append(c.refs[0])
    c.literals.append("extra")
    c.classes.append("extra")
    c.name = "mutated"
    g.components.clear()
    g2 = entity_graph.parse(raw, "F")
    assert g2.name == "F" and len(g2.components) == 1
    c2 = g2.components[0]
    assert c2.name == "Name"
    assert [r.path for r in c2.refs] == [_OTHER]
    assert c2.literals == ["lit_string"]
    assert c2.classes == ["oCEntityCpntPicker", "oCThing"]
    assert c2.refs is not c.refs


def test_entity_graph_copy_equals_original_component():
    raw = _entity_bytes()
    first = entity_graph.parse(raw, "E").components[0]
    again = entity_graph.parse(raw, "E").components[0]
    assert first == again and first is not again
    assert first.refs[0] is not again.refs[0]


def test_corpus_rels_returns_fresh_list_and_follows_the_mirror(tmp_path, monkeypatch):
    one, two = tmp_path / "one", tmp_path / "two"
    for root, rel in ((one, "Zed/a.gen"), (two, "Zed/b.gen")):
        (root / "Zed").mkdir(parents=True)
        (root / rel).write_bytes(b"")
    monkeypatch.setattr(corpus, "UNCOOKED", one)
    first = corpus.rels("Zed/", ".gen")
    first.append("junk")
    assert corpus.rels("Zed/", ".gen") == ["Zed/a.gen"]
    monkeypatch.setattr(corpus, "UNCOOKED", two)
    assert corpus.rels("Zed/", ".gen") == ["Zed/b.gen"]


def test_entity_graph_non_bytes_matches_bytes():
    raw = _entity_bytes()
    assert entity_graph.parse(bytearray(raw), "E") == entity_graph.parse(raw, "E")


@pytest.fixture
def install_cache(monkeypatch):
    monkeypatch.delenv("RSMM_GAME_DIR", raising=False)
    monkeypatch.setattr(paths, "_install_hit", None)
    yield
    paths._install_hit = None


def _install(root: Path) -> Path:
    (root / paths.COOKING_SUBDIR).mkdir(parents=True)
    return root


def test_find_game_dir_override_honored_after_cached_scan(tmp_path, monkeypatch, install_cache):
    from rsmm.cli import apply_mods
    a = _install(tmp_path / "a")
    b = _install(tmp_path / "b")
    monkeypatch.setattr(paths, "_game_dir_candidates", lambda: [a])
    assert apply_mods.find_game_dir() == a
    monkeypatch.setenv("RSMM_GAME_DIR", str(b))
    assert apply_mods.find_game_dir() == b
    monkeypatch.setenv("RSMM_GAME_DIR", str(tmp_path / "nowhere"))
    assert apply_mods.find_game_dir() is None


def test_find_install_dir_rescans_when_hit_removed(tmp_path, monkeypatch, install_cache):
    import shutil
    a = _install(tmp_path / "a")
    b = _install(tmp_path / "b")
    monkeypatch.setattr(paths, "_game_dir_candidates", lambda: [a, b])
    assert paths.find_install_dir() == a
    shutil.rmtree(a / paths.COOKING_SUBDIR)
    assert paths.find_install_dir() == b


def test_find_install_dir_hit_skips_candidate_scan(tmp_path, monkeypatch, install_cache):
    a = _install(tmp_path / "a")
    calls = []

    def cands():
        calls.append(1)
        return [a]

    monkeypatch.setattr(paths, "_game_dir_candidates", cands)
    assert paths.find_install_dir() == a
    assert paths.find_install_dir() == a
    assert len(calls) == 1


def test_find_install_dir_none_not_cached(tmp_path, monkeypatch, install_cache):
    a = tmp_path / "a"
    monkeypatch.setattr(paths, "_game_dir_candidates", lambda: [a])
    assert paths.find_install_dir() is None
    _install(a)
    assert paths.find_install_dir() == a


def _reference_synthesize(decoded, dec2enc):
    """The original linear-scan algorithm, kept as the equivalence oracle."""
    decoded = decoded.replace("\\", "/")
    if "/" not in decoded:
        return cipher.encode(decoded)
    parent, _, fname = decoded.rpartition("/")
    for dec, enc in dec2enc.items():
        dec = dec.replace("\\", "/")
        if "/" not in dec:
            continue
        if dec.rsplit("/", 1)[0] != parent:
            continue
        cut = max(enc.rfind("\\"), enc.rfind("!"))
        if cut == -1:
            continue
        return enc[: cut + 1] + cipher.encode(fname)
    return None


def _small_map():
    bs = chr(92)
    return {
        "top": "TOP",                              # top-level, skipped
        "A/B/one": "xx" + bs + "yy" + bs + "one",  # backslash cut
        "C/D/two": "zz!two",                       # bang cut
        "E/F/bare": "nocut",                       # cut == -1, skipped
        "E/F/good": "ee" + bs + "ff!good",         # later sibling wins
        "G" + bs + "H" + bs + "back": "gg" + bs + "back",  # backslash decoded key
    }


@pytest.mark.parametrize("decoded", [
    "A/B/new", "C/D/new", "E/F/new", "Q/R/new", "top2", "G/H/new",
    "G" + chr(92) + "H" + chr(92) + "new2", "A" + chr(92) + "B" + chr(92) + "n3",
])
def test_synthesize_encoded_matches_the_linear_scan(decoded):
    m = _small_map()
    assert apply_mods.synthesize_encoded(decoded, m) == _reference_synthesize(decoded, m)


def test_synthesize_encoded_sees_entries_added_to_the_same_dict():
    m = _small_map()
    assert apply_mods.synthesize_encoded("Q/R/new", m) is None
    m["Q/R/sib"] = "qq" + chr(92) + "sib"
    got = apply_mods.synthesize_encoded("Q/R/new", m)
    assert got is not None
    assert got == _reference_synthesize("Q/R/new", m)


def test_synthesize_encoded_matches_the_linear_scan_on_the_real_install():
    if corpus.cooking_dir() is None:
        pytest.skip("no game install")
    from rsmm.engine.asset_map import decoded_to_encoded
    m = decoded_to_encoded()
    # The oracle is the slow linear scan, so check one cache path per parent
    # directory, capped, rather than every path.
    by_parent = {}
    for rel in corpus.rels("Definitions/") + corpus.rels("EntitySettings/"):
        try:
            path = rsc_cache.cache_path_for(rel)
        except rsc_cache.CacheError:
            continue
        by_parent.setdefault(path.replace(chr(92), "/").rpartition("/")[0], path)
    sample = [by_parent[k] for k in sorted(by_parent)][:40]
    assert sample
    for path in sample:
        assert apply_mods.synthesize_encoded(path, m) == _reference_synthesize(path, m)


def _fake_corpus(tmp_path, monkeypatch, name="a"):
    """A fake install holding one asset, RSMM_GAME_DIR pointed at it, no mirror."""
    root = _install(tmp_path / name)
    live = root / paths.COOKING_SUBDIR / "enc"
    live.write_bytes(b"live-" + name.encode())
    monkeypatch.setenv("RSMM_GAME_DIR", str(root))
    monkeypatch.setattr(corpus, "UNCOOKED", tmp_path / "no-mirror")
    monkeypatch.setattr(corpus, "_cooking_memo", None)
    monkeypatch.setattr(corpus, "_mirror_memo", None)
    import rsmm.engine.asset_map as am
    monkeypatch.setattr(am, "decoded_to_encoded", lambda: {"X/y": "enc"})
    return root, live


def test_corpus_read_sees_game_dir_switch_at_once(tmp_path, monkeypatch):
    _, _ = _fake_corpus(tmp_path, monkeypatch, "a")
    assert corpus.read("X/y") == b"live-a"
    b = _install(tmp_path / "b")
    (b / paths.COOKING_SUBDIR / "enc").write_bytes(b"live-b")
    monkeypatch.setenv("RSMM_GAME_DIR", str(b))
    assert corpus.read("X/y") == b"live-b"
    monkeypatch.setenv("RSMM_GAME_DIR", str(tmp_path / "nowhere"))
    assert corpus.read("X/y") is None
    assert corpus.cooking_dir() is None


def test_corpus_read_prefers_backup_over_live(tmp_path, monkeypatch):
    _, live = _fake_corpus(tmp_path, monkeypatch)
    assert corpus.read("X/y") == b"live-a"
    assert corpus.install_copies("X/y") == [live]
    bak = live.with_name(live.name + ".rsmm.bak")
    bak.write_bytes(b"pristine")
    assert corpus.read("X/y") == b"pristine"
    assert corpus.install_copies("X/y") == [live, bak]
    assert corpus.install_path("X/y") == bak
    live.unlink()
    assert corpus.read("X/y") == b"pristine"


def test_corpus_read_never_falls_back_past_an_unreadable_backup(tmp_path, monkeypatch):
    _, live = _fake_corpus(tmp_path, monkeypatch)
    bak = live.with_name(live.name + ".rsmm.bak")
    bak.write_bytes(b"pristine")
    real = Path.read_bytes

    def locked(self):
        if self == bak:
            raise PermissionError(self)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    assert corpus.read("X/y") is None


def test_corpus_mirror_miss_memo_follows_uncooked_path(tmp_path, monkeypatch):
    _fake_corpus(tmp_path, monkeypatch)
    assert corpus.mirror_path("X/y") is None
    assert corpus.read("X/y") == b"live-a"
    mirror = tmp_path / "mirror"
    (mirror / "X").mkdir(parents=True)
    (mirror / "X" / "y").write_bytes(b"mirror")
    monkeypatch.setattr(corpus, "UNCOOKED", mirror)
    assert corpus.mirror_path("X/y") == mirror / "X" / "y"
    assert corpus.read("X/y") == b"mirror"
    monkeypatch.setattr(corpus, "UNCOOKED", tmp_path / "gone")
    assert corpus.read("X/y") == b"live-a"


def test_corpus_rels_sees_a_file_added_under_an_existing_mirror(tmp_path, monkeypatch):
    (tmp_path / "Zed").mkdir()
    (tmp_path / "Zed" / "a.gen").write_bytes(b"")
    monkeypatch.setattr(corpus, "UNCOOKED", tmp_path)
    monkeypatch.setattr(corpus, "_mirror_memo", None)
    assert corpus.rels("Zed/", ".gen") == ["Zed/a.gen"]
    (tmp_path / "Zed" / "b.gen").write_bytes(b"")
    assert corpus.rels("Zed/", ".gen") == ["Zed/a.gen", "Zed/b.gen"]


def test_corpus_rels_follows_an_asset_map_rebuild(tmp_path, monkeypatch):
    _fake_corpus(tmp_path, monkeypatch)
    import rsmm.engine.asset_map as am
    current = {"X/y": "enc"}
    monkeypatch.setattr(am, "decoded_to_encoded", lambda: current)
    monkeypatch.setattr(corpus, "_asset_rels_memo", None)
    assert corpus.rels("X/", "") == ["X/y"]
    assert corpus.rels("X/", "") == ["X/y"]
    current = {"X/y": "enc", "X/z": "enc2"}      # a rebuild returns a new dict
    assert corpus.rels("X/", "") == ["X/y", "X/z"]


def test_synthesize_encoded_sees_an_in_place_value_change():
    m = {"X/one": "first!one"}
    assert apply_mods.synthesize_encoded("X/two", m) == "first!" + cipher.encode("two")
    m["X/one"] = "second!one"
    assert apply_mods.synthesize_encoded("X/two", m) == "second!" + cipher.encode("two")


def test_find_install_dir_prefers_a_candidate_that_turns_valid_later(
        tmp_path, monkeypatch, install_cache):
    a = tmp_path / "preferred"
    b = _install(tmp_path / "fallback")
    now = [100.0]
    monkeypatch.setattr(paths, "_monotonic", lambda: now[0])
    monkeypatch.setattr(paths, "_game_dir_candidates", lambda: [a, b])
    assert paths.find_install_dir() == b
    _install(a)
    now[0] += 1.0
    assert paths.find_install_dir() == b          # inside the window: no rescan
    now[0] += paths._INSTALL_HIT_TTL
    assert paths.find_install_dir() == a
