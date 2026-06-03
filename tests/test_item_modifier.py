"""Unit tests for the GUID-targeted value-node swap (base<->super stat swap)."""

import struct

import pytest

from rsmm.engine.item_modifier import swap_guids, value_node_guids


def _lstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


GA = bytes(range(16))
GB = bytes(range(16, 32))
GC = bytes(range(32, 48))


def _blob() -> bytes:
    # Two distinct "Damage Value" nodes (GA gameplay, GC card-count) + a
    # "Attack Speed Value" node (GB), each as <guid><name>, plus a bare ref.
    return (
        b"\x11\x11\xbb\xaa"
        + GA + _lstr("Damage Value")
        + GB + _lstr("Attack Speed Value")
        + GC + _lstr("Damage Value")          # same name, different node
        + GA                                   # a second ref to the gameplay node
        + b"\x22\x22\xbb\xaa"
    )


def test_value_node_guids_reports_ambiguity():
    guids = value_node_guids(_blob(), "Damage Value")
    assert guids == [GA, GC]  # two distinct nodes share the name


def test_swap_guids_length_preserving_and_symmetric():
    raw = _blob()
    out = swap_guids(raw, GA, GB)
    assert len(out) == len(raw)
    # every GA became GB and vice versa; GC (the card-count node) untouched
    assert out.count(GA) == raw.count(GB)
    assert out.count(GB) == raw.count(GA)
    assert out.count(GC) == raw.count(GC)


def test_swap_guids_rejects_identical_and_missing():
    raw = _blob()
    with pytest.raises(ValueError):
        swap_guids(raw, GA, GA)
    with pytest.raises(ValueError):
        swap_guids(raw, GA, bytes(range(48, 64)))  # not present
