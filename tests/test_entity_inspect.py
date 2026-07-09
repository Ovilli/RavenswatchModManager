"""Unit tests for cooked entity inspection helpers."""

from __future__ import annotations

import struct

from rsmm.engine import cooked
from rsmm.engine import entity_inspect as EI


def _lstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def _sample(label: str, extra_string: str) -> bytes:
    payload0 = b""
    payload1 = _lstr(label) + b"\x11\x11\xbb\xaa" + _lstr(extra_string) + b"\x22\x22\xbb\xaa"
    cf = cooked.CookedFile(
        variant="A", hdr_a=0x10, flags=1, extra=0, type_tag=0x31,
        classes=[cooked.ClassDef("oCEntitySettingsResource", 0x16F5F7A3, 1, 0, 0)],
        sections=[cooked.Section(payload=payload0), cooked.Section(payload=payload1)],
    )
    return cooked.emit(cf)


def test_summarize_entity_reports_strings_and_structure():
    raw = _sample("Damage Value", "Quick_Guide_Intro_Title")
    summary = EI.summarize_entity(raw, path="page-a")
    assert summary.path == "page-a"
    assert summary.variant == "A"
    assert summary.section_sizes == tuple(len(s.payload) for s in cooked.parse(raw).sections)
    assert summary.classes[0].name == "oCEntitySettingsResource"
    assert "Damage Value" in summary.strings
    assert "Quick_Guide_Intro_Title" in summary.strings


def test_diff_entities_reports_string_delta():
    left = _sample("Damage Value", "Quick_Guide_Intro_Title")
    right = _sample("Attack Speed Value", "RSMM_Menu_Title")
    diff = EI.diff_entities(left, right, left_path="left", right_path="right")
    assert diff.same_classes
    assert not diff.same_section_sizes
    assert "Damage Value" in diff.only_left_strings
    assert "Attack Speed Value" in diff.only_right_strings


def test_format_diff_includes_samples():
    left = _sample("Damage Value", "Quick_Guide_Intro_Title")
    right = _sample("Attack Speed Value", "RSMM_Menu_Title")
    text = "\n".join(EI.format_diff(EI.diff_entities(left, right), max_strings=3))
    assert "same_variant:" in text
    assert "only_left_strings:" in text
    assert "Damage Value" in text
    assert "Attack Speed Value" in text
