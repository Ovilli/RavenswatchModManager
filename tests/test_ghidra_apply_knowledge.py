"""Which names `tools/ghidra_apply_knowledge.py` carries into a new build."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import ghidra_apply_knowledge as K  # noqa: E402


def test_symbol_map_entries_skip_unverified_and_carry_the_note():
    got = K.symbol_entries([
        {"name": "A", "raw": "FUN_140001000", "status": "ok", "signature": "void()", "note": "n"},
        {"name": "B", "va": "0x141000000", "status": "va"},
        {"name": "C", "raw": "FUN_140002000", "status": "unverified"},
    ])
    assert [(e["name"], e["addr"], e["kind"], e["force"]) for e in got] == [
        ("A", "0x140001000", "function", True), ("B", "0x141000000", "data", True)]
    assert got[0]["note"].startswith("[rsmm ok] A :: void()\nn")


def test_bindiff_ports_only_real_unambiguous_names_onto_default_ones(tmp_path):
    db = tmp_path / "x.BinDiff"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE function (address1, address2, similarity, confidence, name1, name2)")
    con.executemany("INSERT INTO function VALUES (?,?,?,?,?,?)", [
        (1, 0x10, 0.99, 0.99, "Good_Name", "FUN_10"),       # ported
        (2, 0x20, 0.99, 0.99, "sub_140002", "FUN_20"),      # BinExport default name
        (3, 0x30, 0.50, 0.99, "Weak_Match", "FUN_30"),      # below threshold
        (4, 0x40, 0.99, 0.99, "Has_Name", "Already_Named"),  # new side named
        (5, 0x50, 0.99, 0.99, "Twice", "FUN_50"),           # ambiguous: dropped
        (6, 0x60, 0.99, 0.99, "Twice", "FUN_60"),
        (7, 0x70, 0.99, 0.99, "In_Map", "FUN_70"),          # symbols.json owns it
    ])
    con.commit()
    con.close()
    got = K.bindiff_entries(db, {"In_Map"}, set(), min_sim=0.9, min_conf=0.9, old_tag="old")
    assert [(e["name"], e["addr"], e["force"]) for e in got] == [("Good_Name", "0x10", False)]
