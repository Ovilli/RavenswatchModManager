"""tools/update_symbols.py — the patch-day helpers, on synthetic PE files (no game bytes)."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "scripts"))

us = pytest.importorskip("update_symbols")

BASE = 0x140000000
TEXT_RVA, PDATA_RVA = 0x1000, 0x3000


def make_pe(path: Path, funcs: dict[int, bytes]) -> Path:
    """A minimal PE32+: .text holding `funcs` (rva -> code) and a .pdata naming them."""
    text = bytearray(0x2000)
    for rva, code in funcs.items():
        text[rva - TEXT_RVA:rva - TEXT_RVA + len(code)] = code
    pdata = b"".join(struct.pack("<III", rva, rva + len(code), 0)
                     for rva, code in sorted(funcs.items()))
    pdata = pdata.ljust(0x200, b"\0")
    e_lfanew, opt_size = 0x40, 0xF0
    hdr = bytearray(0x400)
    struct.pack_into("<I", hdr, 0x3C, e_lfanew)
    hdr[e_lfanew:e_lfanew + 4] = b"PE\0\0"
    coff = e_lfanew + 4
    struct.pack_into("<HHIIIHH", hdr, coff, 0x8664, 2, 0, 0, 0, opt_size, 0x22)
    opt = coff + 20
    struct.pack_into("<H", hdr, opt, 0x20B)
    struct.pack_into("<Q", hdr, opt + 24, BASE)
    struct.pack_into("<II", hdr, opt + 112 + 3 * 8, PDATA_RVA, len(funcs) * 12)
    sec = opt + opt_size
    raw_text, raw_pdata = 0x400, 0x400 + len(text)
    for i, (name, rva, size, raw) in enumerate(((b".text", TEXT_RVA, len(text), raw_text),
                                                (b".pdata", PDATA_RVA, len(pdata), raw_pdata))):
        o = sec + 40 * i
        hdr[o:o + 8] = name.ljust(8, b"\0")
        struct.pack_into("<IIII", hdr, o + 8, size, rva, size, raw)
    path.write_bytes(bytes(hdr) + bytes(text) + pdata)
    return path


def call(src_rva: int, dst_rva: int) -> bytes:
    return b"\xe8" + struct.pack("<i", dst_rva - (src_rva + 5))


def test_callers_map_each_site_to_its_function(tmp_path):
    # A (0x1000) calls B (0x1100) at its second instruction; C (0x1200) tail-jumps to B.
    a = b"\x90" + call(0x1001, 0x1100) + b"\xc3"
    c = b"\xe9" + struct.pack("<i", 0x1100 - (0x1200 + 5))
    img = us.Image(make_pe(tmp_path / "x.exe", {0x1000: a, 0x1100: b"\xc3", 0x1200: c}))
    sites = us.call_sites(img, BASE + 0x1100)
    assert sites == [(BASE + 0x1001, "call"), (BASE + 0x1200, "jmp")]
    assert [img.containing(s) for s, _ in sites] == [BASE + 0x1000, BASE + 0x1200]
    assert img.containing(BASE + 0x1F00) is None


def _symbols(path: Path, names: dict[str, int]) -> Path:
    path.write_text(json.dumps({"symbols": [
        {"name": n, "kind": "function", "status": "ok", "raw": f"FUN_{va:x}"}
        for n, va in names.items()]}))
    return path


def test_audit_flags_a_wrong_match_and_passes_a_moved_twin(tmp_path):
    pytest.importorskip("capstone")
    same = bytes.fromhex("4883ec28" "488b4108" "4883c428" "c3")          # sub/mov/add/ret
    other = bytes.fromhex("31c0" "ffc0" "ffc0" "ffc0" "ffc0" "c3")       # xor/inc x4/ret
    old = make_pe(tmp_path / "old.exe", {0x1000: same, 0x1100: same + b"\x90"})
    new = make_pe(tmp_path / "new.exe", {0x1040: same, 0x1140: other})
    o = _symbols(tmp_path / "o.json", {"Good": BASE + 0x1000, "Wrong": BASE + 0x1100})
    n = _symbols(tmp_path / "n.json", {"Good": BASE + 0x1040, "Wrong": BASE + 0x1140})
    rows = {r["name"]: r for r in us.audit_pairs(
        us.Image(old), us.Image(new),
        {k: (us.function_addrs(json.loads(o.read_text()))[k],
             us.function_addrs(json.loads(n.read_text()))[k]) for k in ("Good", "Wrong")})}
    assert rows["Good"]["ratio"] == 1.0
    assert not us._flags(rows["Good"], 0.97, patched=True)
    assert any(f.startswith("body") for f in us._flags(rows["Wrong"], 0.97, patched=True))
    assert us.audit(old, new, o, n, 0.97, None) == 1


def test_fields_votes_follow_a_shifted_struct_field(tmp_path):
    pytest.importorskip("capstone")
    # mov rax,[rcx+0x1d0]; mov eax,[rcx+8]; ret  ->  +0x18 on the first field only
    old_code = bytes.fromhex("488b81d0010000" "8b4108" "c3")
    new_code = bytes.fromhex("488b81e8010000" "8b4108" "c3")
    old = us.Image(make_pe(tmp_path / "old.exe", {0x1000: old_code}))
    new = us.Image(make_pe(tmp_path / "new.exe", {0x1010: new_code}))
    votes = us.field_votes(old, new, BASE + 0x1000, BASE + 0x1010)
    assert votes[0x1D0].most_common(1)[0][0] == 0x1E8
    assert votes[0x8].most_common(1)[0][0] == 0x8


def test_preflight_stops_on_leftover_backups(tmp_path, monkeypatch, capsys):
    game = tmp_path / "game"
    cooking = game / us.COOKING
    cooking.mkdir(parents=True)
    (cooking / ".rsmm_state.json").write_text(json.dumps({"active": {}}))
    (game / "Ravenswatch.exe").write_bytes(b"exe")
    monkeypatch.delenv("RSMM_GHIDRA_PROJECT", raising=False)
    monkeypatch.setattr(us, "PATTERN_META", tmp_path / "meta.json")
    assert us.preflight(game) == 0
    project = tmp_path / "ghidra"
    project.mkdir()
    monkeypatch.setenv("RSMM_GHIDRA_PROJECT", str(project))
    assert us.preflight(game) == 0
    (project / "Ravenswatch.lock").write_bytes(b"")
    assert us.preflight(game) == 1
    (project / "Ravenswatch.lock").unlink()
    (cooking / "abc.yqz.rsmm.bak").write_bytes(b"")
    assert us.preflight(game) == 1
    assert "backups left" in capsys.readouterr().out


def test_snapshot_copies_the_build_and_refuses_a_modded_install(tmp_path):
    steamapps = tmp_path / "steamapps"
    game = steamapps / "common" / "Ravenswatch"
    cooking = game / us.COOKING
    cooking.mkdir(parents=True)
    (game / "Ravenswatch.exe").write_bytes(b"exe bytes")
    (cooking / "abc.yqz").write_bytes(b"cooked")
    (steamapps / "appmanifest_2071280.acf").write_text(
        '"AppState"\n{\n\t"buildid"\t\t"123"\n\t"installdir"\t\t"Ravenswatch"\n}\n')
    out = tmp_path / "snaps"
    assert us.snapshot(game, out, versions=False) == 0
    (dest,) = out.iterdir()
    assert dest.name == us._sha256(game / "Ravenswatch.exe")[:12]
    assert (dest / f"Ravenswatch-{dest.name}.exe").read_bytes() == b"exe bytes"
    assert (dest / "appmanifest_2071280.acf").is_file()
    listed = (dest / "listing.tsv").read_text(encoding="utf-8").splitlines()
    assert f"{us.COOKING}/abc.yqz\t6" in listed
    assert len((dest / "sha256sums.txt").read_text(encoding="utf-8").splitlines()) == 2

    (cooking / "abc.yqz.rsmm.bak").write_bytes(b"")
    assert us.snapshot(game, tmp_path / "snaps2", versions=False) == 1
    assert not (tmp_path / "snaps2").exists()


def test_class_version_diff_reports_a_recook(tmp_path, monkeypatch):
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"oCDamage": ["1.21"], "oCSame": ["2.0"]}))
    monkeypatch.setattr(us, "class_versions",
                        lambda game: {"oCDamage": ["1.23"], "oCSame": ["2.0"]})
    assert us.class_versions_cmd(tmp_path, None, base) == 1


def test_rebuild_warns_on_a_big_pattern_count_drop():
    from rsmm.cli import cmd_rebuild_patterns as R
    assert "down from 65,328" in R._count_drop(65_328, 50_085)
    assert R._count_drop(65_328, 65_153) is None
    assert R._count_drop(None, 100) is None
