"""tools/va_locators.py — patch-survivable locators for the `status=va` globals."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "scripts"))

va_locators = pytest.importorskip("va_locators")


def test_shape_wildcards_only_the_disp():
    # mov rax, [rip+0x11223344] ; 48 8b 05 <disp32>
    insn = bytes.fromhex("488b0544332211")
    assert va_locators._shape(insn, 3) == "48 8b 05 ?? ?? ?? ??"
    # cmp dword ptr [rip+disp], 5 ; the trailing imm8 must survive the mask
    insn = bytes.fromhex("833d4433221105")
    assert va_locators._shape(insn, 2) == "83 3d ?? ?? ?? ?? 05"


def test_capture_refuses_to_overwrite_another_builds_locators(tmp_path, monkeypatch):
    # Capturing on a patched exe before `recover` would record the OLD vas as if
    # they were valid in the new build. The guard must stop that.
    out = tmp_path / "va_locators.json"
    out.write_text(json.dumps({"exe_sha256": "a" * 64, "symbols": {}}))
    monkeypatch.setattr(va_locators, "OUT", out)
    assert va_locators.capture(SimpleNamespace(sha="b" * 64), force=False) == 2
    assert json.loads(out.read_text())["exe_sha256"] == "a" * 64


@pytest.mark.slow
def test_locators_reproduce_todays_addresses():
    """On the capture exe every locator must resolve to the current `va`."""
    pytest.importorskip("capstone")
    if not va_locators.OUT.is_file():
        pytest.skip("data/va_locators.json not captured (gitignored)")
    exe_path = Path(va_locators.gen.DEFAULT_EXE)
    if not exe_path.is_file():
        pytest.skip("game exe not installed")
    exe = va_locators.Exe(exe_path)
    if json.loads(va_locators.OUT.read_text())["exe_sha256"] != exe.sha:
        pytest.skip("locators were captured from a different build")
    assert va_locators.verify(exe) == 0
