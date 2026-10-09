"""The loader's WinHTTP pass-through thunks stay in step with exports/winhttp.def."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEF = ROOT / "src" / "loader" / "exports" / "winhttp.def"


def test_generated_thunks_match_the_def():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_winhttp_thunks.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_nothing_forwards_to_the_renamed_copy_any_more():
    # A forwarder can only name the real WinHTTP by base name, which on native
    # Windows meant a renamed copy of the system DLL -- and that broke every
    # online request (2026-10-09). Pass-through goes through a thunk instead.
    text = DEF.read_text(encoding="utf-8")
    assert "winhttp_real." not in text
    exports = [line.strip() for line in text.splitlines()[2:] if "=" in line]
    odd = [e for e in exports if not e.split("=")[1].startswith(("rsmm_fwd_", "rsmm_WinHttp"))]
    assert not odd, f"every export is a thunk or a loader wrapper: {odd}"
