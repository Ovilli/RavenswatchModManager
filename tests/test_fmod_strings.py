"""FMOD strings-bank path decoder + the `fmod-sounds` config option source."""

from __future__ import annotations

import struct

import pytest

from rsmm.engine import fmod_strings as F


def _bank(paths: list[str]) -> bytes:
    """A minimal RIFF/STDT strings bank in the layout `fmod_strings` reads:
    a radix trie whose nodes branch on the LOWER-CASED first label byte, a
    header the parser does not interpret, junk between nodes and pool."""
    trie: dict = {}
    for p in paths:
        node = trie
        for ch in p:
            node = node.setdefault(ch, {})
        node[""] = {}

    # Compress single-child chains into labels.
    def compress(node: dict) -> list[tuple[str, dict]]:
        out = []
        for ch, child in sorted(node.items()):
            if ch == "":
                out.append(("", {}))
                continue
            label = ch
            while len(child) == 1 and "" not in child:
                (nch, nchild), = child.items()
                label += nch
                child = nchild
            out.append((label, child))
        return out

    nodes: list[list] = [[0xFFFFFF, 0, 0, 0]]
    pool = bytearray()

    def build(idx: int, node: dict) -> None:
        kids = compress(node)
        first = len(nodes)
        nodes[idx][2], nodes[idx][3] = first, len(kids)
        for label, _ in kids:
            if label:
                off = len(pool)
                pool.extend(label.encode() + b"\0")
                nodes.append([off, ord(label[0].lower()), 0, 0])
            else:
                nodes.append([0xFFFFFF, 0, 0, 0])
        for j, (label, child) in enumerate(kids):
            if label:
                build(first + j, child)

    build(0, trie)
    body = struct.pack("<II", 1, 0xDEADBEEF)
    for lo, ch, child, nc in nodes:
        body += struct.pack("<II", lo | (ch << 24), child | (nc << 24))
    body += b"\x9a\x11" * 7 + bytes(pool)
    stdt = b"STDT" + struct.pack("<I", len(body)) + body
    fev = b"FEV " + stdt
    return b"RIFF" + struct.pack("<I", len(fev)) + fev


PATHS = [
    "bank:/Master", "bank:/Master.strings", "bus:/", "bus:/Music", "bus:/SFX/GUI",
    "event:/Heroes/Red/Human/Attack", "event:/Heroes/Red/Wolf/Howl",
    "event:/Heroes/Piper/Rats", "event:/GUI/Click", "vca:/Foes_Ghouls",
]


def test_parse_round_trips_every_path():
    assert F.parse(_bank(PATHS)) == sorted(PATHS)


def test_a_path_that_is_a_prefix_of_another_is_kept():
    out = F.parse(_bank(["bus:/", "bus:/Music", "bus:/Music/MUSIC"]))
    assert out == ["bus:/", "bus:/Music", "bus:/Music/MUSIC"]


def test_upper_case_labels_match_their_folded_key():
    # Every label here starts upper-case after the scheme, which is the case
    # the first decoder got wrong (it compared the key byte raw).
    out = F.parse(_bank(["event:/Alpha/Beta", "event:/Alpha/Gamma"]))
    assert out == ["event:/Alpha/Beta", "event:/Alpha/Gamma"]


def test_corrupt_trie_raises_instead_of_guessing():
    data = bytearray(_bank(PATHS))
    i = data.find(b"STDT") + 8
    # Point node 1's first char at something no label starts with.
    word = struct.unpack_from("<I", data, i + 16)[0]
    struct.pack_into("<I", data, i + 16, (word & 0xFFFFFF) | (ord("~") << 24))
    with pytest.raises(F.FmodStringsError):
        F.parse(bytes(data))


def test_not_a_bank():
    with pytest.raises(F.FmodStringsError):
        F.parse(b"nope")


def test_bank_path_is_the_ciphered_strings_bank(tmp_path):
    assert F.bank_path(tmp_path).name == "Hgviqu.viudzyv.agzm"


def test_fmod_sounds_provider(monkeypatch, tmp_path):
    from rsmm.cli import apply_mods as A
    from rsmm.sdk.config_choices import PROVIDERS, provide

    assert "fmod-sounds" in PROVIDERS
    monkeypatch.setattr(A, "find_game_dir", lambda: tmp_path)
    monkeypatch.setattr(F, "paths", lambda game_dir: sorted(PATHS))
    opts = provide("fmod-sounds")
    ids = [o["id"] for o in opts]
    assert ids[0] == "all"
    assert "bus:/" not in ids                    # the master is "all"
    assert {"bus:/Music", "bus:/SFX/GUI"} <= set(ids)
    # Folders down to three levels, never a single event.
    assert {"event:/Heroes", "event:/Heroes/Red", "event:/Heroes/Red/Human"} <= set(ids)
    assert "event:/Heroes/Red/Human/Attack" not in ids
    assert "event:/GUI/Click" not in ids and "event:/GUI" in ids
    red = next(o for o in opts if o["id"] == "event:/Heroes/Red")
    assert red["group"] == "Sounds: Heroes" and "2 sounds" in red["description"]
    assert not any(o["id"].startswith(("vca:/", "bank:/")) for o in opts)


def test_provider_is_empty_without_a_game(monkeypatch):
    from rsmm.cli import apply_mods as A
    from rsmm.sdk.config_choices import provide

    monkeypatch.setattr(A, "find_game_dir", lambda: None)
    assert provide("fmod-sounds") == []


def test_real_bank_if_installed():
    from rsmm.cli import apply_mods as A

    game = A.find_game_dir()
    if game is None or not F.bank_path(game).is_file():
        pytest.skip("no Ravenswatch install")
    out = F.paths(game)
    assert "bus:/" in out and "bank:/Master" in out
    assert sum(p.startswith("event:/") for p in out) > 1000


def test_folder_source_lists_every_event_in_it(monkeypatch, tmp_path):
    from rsmm.cli import apply_mods as A
    from rsmm.sdk.config_choices import provide

    monkeypatch.setattr(A, "find_game_dir", lambda: tmp_path)
    monkeypatch.setattr(F, "paths", lambda game_dir: sorted(PATHS))
    opts = provide("fmod-sounds:event:/Heroes/Red")
    ids = [o["id"] for o in opts]
    assert ids[0] == "event:/Heroes/Red"                       # the whole list
    assert {"event:/Heroes/Red/Human", "event:/Heroes/Red/Wolf"} <= set(ids)
    assert {"event:/Heroes/Red/Human/Attack", "event:/Heroes/Red/Wolf/Howl"} <= set(ids)
    assert not any("Piper" in i for i in ids)
    howl = next(o for o in opts if o["id"].endswith("/Howl"))
    assert howl["group"] == "Wolf" and howl["label"] == "Howl"


def test_folder_source_argument_is_validated():
    from rsmm.sdk.config_choices import split_source

    assert split_source("fmod-sounds:event:/Heroes/Red") == ("fmod-sounds", "event:/Heroes/Red")
    assert split_source("fmod-sounds") == ("fmod-sounds", None)
    for bad in ("fmod-sounds:bus:/Music", "fmod-sounds:/etc/passwd", "item-catalog:x", "nope"):
        with pytest.raises(ValueError):
            split_source(bad)


def test_hero_code_is_dropped_from_event_labels():
    from rsmm.sdk.config_choices import _fmod_event_label

    assert _fmod_event_label("HRh_PrimaryFinisher_Anim") == "Primary Finisher Anim"
    assert _fmod_event_label("HSW_Ultimate2_Anim_Out") == "Ultimate2 Anim Out"
    assert _fmod_event_label("Chest_Closing") == "Chest Closing"
