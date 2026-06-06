"""Tests for the loader-DLL static smoke-test (scripts/validate_loader_dll.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "validate_loader_dll.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_loader_dll", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


vld = _load_module()


def test_missing_file_fails(tmp_path: Path):
    with pytest.raises(vld.ValidationError, match="does not exist"):
        vld.validate(tmp_path / "nope.dll")


def test_tiny_file_fails(tmp_path: Path):
    p = tmp_path / "stub.dll"
    p.write_bytes(b"MZ" + b"\0" * 100)
    with pytest.raises(vld.ValidationError, match="stub"):
        vld.validate(p)


def test_non_pe_fails():
    with pytest.raises(vld.ValidationError, match="MZ"):
        vld.parse_exports(b"\x00" * 8192)


def test_mz_without_pe_signature_fails():
    data = bytearray(b"MZ" + b"\0" * 8192)
    # e_lfanew points somewhere with no "PE\0\0".
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    with pytest.raises(vld.ValidationError, match="PE signature"):
        vld.parse_exports(bytes(data))


def test_real_dll_if_present():
    """If a loader DLL has been built locally, it must pass validation."""
    dll = _ROOT / "dist" / "winhttp.dll"
    if not dll.is_file():
        pytest.skip("no built dist/winhttp.dll to validate")
    vld.validate(dll)  # raises on any problem
    exports = vld.parse_exports(dll.read_bytes())
    assert vld.REQUIRED_EXPORTS <= exports
