"""The loader's WinHTTP pass-through thunks stay in step with exports/winhttp.def."""

from __future__ import annotations

import re
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
    # Windows meant a renamed copy of the system DLL. Pass-through goes through
    # a thunk instead, which reaches System32's genuine module.
    text = DEF.read_text(encoding="utf-8")
    assert "winhttp_real." not in text
    exports = [line.strip() for line in text.splitlines()[2:] if "=" in line]
    odd = [e for e in exports if not e.split("=")[1].startswith(("rsmm_fwd_", "rsmm_WinHttp"))]
    assert not odd, f"every export is a thunk or a loader wrapper: {odd}"


def test_every_export_of_windows_winhttp_keeps_its_ordinal():
    # The proxy is THE winhttp.dll for every module in the game process. It
    # lacked five of the real DLL's exports, and that alone kept a Windows
    # player offline (every request "Open failed", no party code) until they
    # were added (2026-10-09). The real table, ordinals included, is
    # winhttp.dll 10.0.19041.5794 from Microsoft's symbol server.
    real = [
        "WinHttpPacJsWorkerMain", "WinHttpSetSecureLegacyServersAppCompat",
        "DllCanUnloadNow", "DllGetClassObject", "Private1", "SvchostPushServiceGlobals",
    ]
    text = DEF.read_text(encoding="utf-8")
    for ordinal, name in enumerate(real, start=1):
        assert re.search(rf"^\s*{name}=\w+ @{ordinal}$", text, re.M), name
    ordinals = [int(line.rsplit("@", 1)[1]) for line in text.splitlines() if " @" in line]
    assert ordinals == list(range(1, len(ordinals) + 1)), "ordinals are dense and in order"
