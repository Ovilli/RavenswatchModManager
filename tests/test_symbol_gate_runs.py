"""Repo scripts must run outside an activated venv, and the gate must not cry wolf.

`./rsmm install-loader` shells its helpers out via `sys.executable`, which is
not necessarily the interpreter an editable install put `rsmm` on. When that
import died, the gate reported the crash as "mid-instruction symbols" and told
the user to go recover addresses — for symbols that were entirely fine.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
VERIFY = SCRIPTS / "verify_symbol_resolve.py"

#: Must stay in sync with verify_symbol_resolve.EXIT_CANNOT_RUN and the literal
#: in install_loader._symbol_resolve_gate.
EXIT_CANNOT_RUN = 3

#: Bare environment: no venv, no inherited PYTHONPATH.
_BARE_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/tmp"}


def _run_bare(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True,
                          env=_BARE_ENV, cwd=str(REPO), check=False)


def _rsmm_importers() -> list[str]:
    out = []
    for p in sorted(SCRIPTS.glob("*.py")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "from rsmm" in text or "import rsmm" in text:
            out.append(p.name)
    return out


@pytest.mark.parametrize("script", _rsmm_importers())
def test_script_starts_without_an_activated_venv(script):
    """Behavioural, not a grep: run `--help` with a bare interpreter and assert
    it does not die importing `rsmm`. Catches the missing sys.path insert
    however the script chooses to spell it."""
    r = _run_bare(SCRIPTS / script, "--help")
    assert "ModuleNotFoundError: No module named 'rsmm'" not in r.stderr, (
        f"{script} cannot run outside a venv:\n{r.stderr}")


def test_verifier_reports_cannot_run_not_failure_when_the_exe_is_missing():
    """A missing exe is 'could not check', not 'the symbols are broken' — the
    difference decides whether install-loader refuses to plant the DLL."""
    r = _run_bare(VERIFY, "--exe", "/nonexistent/Ravenswatch.exe")
    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == EXIT_CANNOT_RUN, (r.returncode, r.stderr)
    assert r.returncode != 1, "1 blocks the install"


def test_install_loader_gate_agrees_on_the_cannot_run_code():
    src = (REPO / "src" / "rsmm" / "cli" / "install_loader.py").read_text()
    assert f"cannot_run = {EXIT_CANNOT_RUN}" in src, (
        "install_loader must treat the verifier's cannot-run code as "
        "skip-and-proceed, not as a failure")
