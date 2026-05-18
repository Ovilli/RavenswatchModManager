"""Every committed mods/<id>/manifest.toml must parse and carry the
fields the rest of RSMM relies on. Catches typos and TOML syntax
breakage before they reach `rsmm apply`."""

import tomllib
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
MODS_DIR = REPO / "mods"

REQUIRED = ("id", "name", "version")


def _manifest_paths():
    if not MODS_DIR.is_dir():
        return []
    out = []
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        mf = entry / "manifest.toml"
        if mf.is_file():
            out.append(mf)
    return out


MANIFESTS = _manifest_paths()


@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda p: p.parent.name)
def test_manifest_parses_and_has_required_fields(manifest_path: Path):
    data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    mod = data.get("mod") or {}
    for field in REQUIRED:
        assert mod.get(field), (
            f"{manifest_path.relative_to(REPO)}: missing or empty `mod.{field}`"
        )


def test_at_least_one_manifest_present():
    assert MANIFESTS, f"no mods found under {MODS_DIR}"
