#!/usr/bin/env python3
"""
Unpack the uncooked FMOD banks into individually playable audio files.

`scripts/extract_uncooked.py` mirrors the banks byte-for-byte, but a `.bank`
is a container — nothing can play it directly. This walks each bank's embedded
FSB5 sub-banks and writes one file per sample, named from the bank's own name
table (e.g. `Carmilla_Voice_Hurt_Small_02.ogg`).

The samples are FSB5 mode 15 (Vorbis). FMOD strips the Vorbis setup headers and
keeps only a CRC key, so the headers have to be rebuilt from a lookup table —
that is what `python-fsb5` does, and why plain ffmpeg cannot read these files.

    pip install fsb5                      # dev-only; not a runtime dependency
    scripts/extract_audio.py                        # -> .ogg (no re-encode)
    scripts/extract_audio.py --wav                  # + .wav via ffmpeg
    scripts/extract_audio.py --filter Hero_Piper    # one bank
    scripts/extract_audio.py --filter Voice_EN --name 'Kintaro|Alice'   # one hero

Output: data/uncooked/Audio/extracted/<BankName>/<SampleName>.<ext>
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

try:
    import fsb5
except ImportError:
    sys.exit("missing dep: pip install fsb5")

REPO = Path(__file__).resolve().parent.parent
AUDIO_DIR = REPO / "data" / "uncooked" / "Audio"
FSB5_MAGIC = b"FSB5"
_SAFE = re.compile(r"[^0-9A-Za-z._-]")


def safe_name(name: str, fallback: str) -> str:
    """Sample names come from the game's own name table; keep them readable but
    filesystem-safe (they can contain spaces, slashes, punctuation)."""
    cleaned = _SAFE.sub("_", name).strip("._")
    return cleaned or fallback


def iter_fsb5(data: bytes):
    """Yield every embedded FSB5 sub-bank. A .bank can hold more than one, so
    scanning only the first (the obvious shortcut) silently drops samples."""
    pos = 0
    while True:
        i = data.find(FSB5_MAGIC, pos)
        if i < 0:
            return
        try:
            sub = fsb5.FSB5(data[i:])
        except Exception:  # noqa: BLE001 - a false FSB5 magic hit inside sample data
            pos = i + 4
            continue
        yield sub
        # Advance past this sub-bank's payload rather than rescanning inside it:
        # compressed sample data can contain the FSB5 magic by chance, which
        # would otherwise re-parse garbage as a sub-bank.
        h = sub.header
        span = h.size + h.sampleHeadersSize + h.nameTableSize + h.dataSize
        pos = i + max(span, 4)


def to_wav(src: Path) -> bool:
    """Transcode to .wav — VS Code and most editors will not play Ogg inline."""
    dst = src.with_suffix(".wav")
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), str(dst)],
        capture_output=True,
    )
    return r.returncode == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audio-dir", default=str(AUDIO_DIR))
    ap.add_argument("--out", default=None, help="default: <audio-dir>/extracted")
    ap.add_argument("--filter", help="substring match on bank filename")
    ap.add_argument(
        "--name",
        help="regex on the SAMPLE name (case-insensitive), e.g. 'Kintaro|Alice'. "
        "Voice_EN.bank alone is 683 MB of samples, so pulling a handful of "
        "lines out of it is the common case, not a special one.")
    ap.add_argument("--wav", action="store_true", help="also write .wav via ffmpeg")
    ap.add_argument("--limit", type=int, help="stop after N samples per bank (testing)")
    a = ap.parse_args(argv)

    audio = Path(a.audio_dir)
    out_root = Path(a.out) if a.out else audio / "extracted"
    want = re.compile(a.name, re.I) if a.name else None
    banks = sorted(p for p in audio.glob("*.bank") if not a.filter or a.filter in p.name)
    if not banks:
        sys.exit(f"no banks matched under {audio}")

    total = failed = 0
    for bank in banks:
        data = bank.read_bytes()
        out_dir = out_root / bank.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for sub in iter_fsb5(data):
            ext = sub.get_sample_extension()
            for idx, sample in enumerate(sub.samples):
                if a.limit and n >= a.limit:
                    break
                # Match on the RAW name, before sanitising: the game's own
                # names carry parentheses and commas (`Spawn_(Kintaro,Merlin)`)
                # that safe_name replaces with underscores, so a pattern the
                # user copied out of the bank would stop matching.
                if want and not want.search(sample.name or ""):
                    continue
                name = safe_name(sample.name or "", f"sample_{idx:05d}")
                dst = out_dir / f"{name}.{ext}"
                try:
                    dst.write_bytes(sub.rebuild_sample(sample))
                except Exception as e:  # noqa: BLE001 - unrebuildable codec; keep going
                    failed += 1
                    if failed <= 5:
                        print(f"  [warn] {bank.name}:{name}: {e}")
                    continue
                if a.wav and not to_wav(dst):
                    failed += 1
                n += 1
        total += n
        print(f"{bank.name:<30} {n:>6} samples -> {out_dir.relative_to(REPO)}", flush=True)

    print(f"\nextracted {total} samples ({failed} failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
