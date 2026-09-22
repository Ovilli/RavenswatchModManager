"""The uncooked mirror must not accumulate files the asset map no longer names.

`scripts/extract_uncooked.py` used to be purely additive: it wrote what the
current `asset_map` named and never removed anything, so a decoded path that
changed spelling left its old file behind forever. That is not inert — after
the 2026-09-22 cipher fix renamed 7307 paths, the mirror held both spellings of
the same level (`40x40_Cross_Plava_Camp` and `..._Plaza_Camp`), and because
they are one level under two names they share a GUID, which broke
`test_poi.py::test_every_shipped_tile_level_has_a_distinct_guid` with an error
that named neither the cipher nor the extractor.

These tests pin the prune and, just as importantly, the cases where it must
refuse — a prune that runs on a partial or failed run deletes good files.
"""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "extract_uncooked.py"

pytest.importorskip("PIL")
pytest.importorskip("texture2ddecoder")


def _cooked(game: Path, encoded: str, body: bytes = b"payload") -> None:
    p = game / "DarkTalesResources" / "_Cooking" / encoded
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)


def _map(tmp: Path, rows: list[tuple[str, str]]) -> Path:
    p = tmp / "asset_map.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["encoded", "decoded"])
        w.writerows(rows)
    return p


def _run(game: Path, amap: Path, out: Path, *extra: str):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--game-dir", str(game), "--asset-map", str(amap),
         "--out", str(out), "--jobs", "1", *extra],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


@pytest.fixture
def world(tmp_path):
    game, out = tmp_path / "game", tmp_path / "out"
    _cooked(game, "aaa.bin")
    _cooked(game, "bbb.bin")
    amap = _map(tmp_path, [("aaa.bin", "Test\\Alpha.bin"), ("bbb.bin", "Test\\Beta.bin")])
    return game, amap, out


def test_renamed_asset_does_not_leave_its_old_spelling(world, tmp_path):
    """The actual bug: rename a decoded path, and the old file must not survive."""
    game, amap, out = world
    _run(game, amap, out)
    assert (out / "Test/Alpha.bin").exists()

    # the cipher fix renames Alpha -> Alpherz; Beta is untouched
    amap2 = _map(tmp_path, [("aaa.bin", "Test\\Alpherz.bin"), ("bbb.bin", "Test\\Beta.bin")])
    stdout = _run(game, amap2, out)

    assert (out / "Test/Alpherz.bin").exists(), "the corrected name was not written"
    assert not (out / "Test/Alpha.bin").exists(), "the old spelling survived the re-run"
    assert (out / "Test/Beta.bin").exists(), "an untouched asset was pruned"
    assert "prune: removed 1 stale files" in stdout


def test_prune_leaves_the_audio_library_alone(world):
    """`Audio/extracted/` is extract_audio.py's, and has no asset_map row."""
    game, amap, out = world
    _run(game, amap, out)
    sample = out / "Audio" / "extracted" / "Music" / "track.ogg"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"ogg")

    _run(game, amap, out)
    assert sample.exists(), "the prune deleted another script's output"


def test_gen_sidecars_follow_their_source(world, tmp_path):
    """A decode_gen_sidecars.py `.gen.txt` lives and dies with its `.gen`."""
    game, out = world[0], world[2]
    _cooked(game, "ccc.bin")
    amap = _map(tmp_path, [("aaa.bin", "Test\\Alpha.gen"), ("ccc.bin", "Test\\Gamma.gen")])
    _run(game, amap, out)
    kept = out / "Test/Alpha.gen.txt"
    orphan = out / "Test/Deleted.gen.txt"
    kept.write_text("decoded")
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("decoded")

    _run(game, amap, out)
    assert kept.exists(), "a sidecar whose .gen still exists was pruned"
    assert not orphan.exists(), "a sidecar whose .gen is gone was kept"


@pytest.mark.parametrize(
    "flags, why",
    [
        (["--no-prune"], "--no-prune"),
        (["--filter", "Alpha"], "partial run"),
        (["--limit", "1"], "partial run"),
    ],
)
def test_prune_refuses_when_the_run_is_not_the_whole_mirror(world, tmp_path, flags, why):
    """A subset run describes a slice; pruning on it would delete the rest."""
    game, amap, out = world
    _run(game, amap, out)
    stray = out / "Test" / "Orphan.bin"
    stray.write_bytes(b"x")

    stdout = _run(game, amap, out, *flags)
    assert stray.exists(), f"pruned despite {why}"
    assert "prune: skipped" in stdout
