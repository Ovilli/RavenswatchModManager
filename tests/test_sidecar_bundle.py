"""The frozen CLI's bundle list lives in one place and points at real files.

Building the sidecar takes PyInstaller and a minute, so the CI `sidecar` job
does it; these are the cheap halves of the same guarantee that run with every
pytest: a renamed or moved data file fails here, and a second copy of the file
list (release.yml used to carry its own) cannot creep back in.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "build-sidecar.py"


def _load():
    spec = importlib.util.spec_from_file_location("build_sidecar", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_required_bundle_entry_exists():
    _present, missing = _load().bundle_entries()
    assert missing == []


def test_workflows_build_the_sidecar_through_the_script():
    release = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/build-sidecar.py --require-loader" in release
    assert "scripts/build-sidecar.py" in ci
    for text in (release, ci):
        assert "--add-data" not in text, "bundle files belong in build-sidecar.py's BUNDLE"
