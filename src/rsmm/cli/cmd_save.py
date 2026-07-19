"""`rsmm save` — inspect Ravenswatch profile saves.

Read-only by design. The container (header, CRC32, class registry) is fully
parsed; the data section is opaque because per-class field layouts are not
reverse-engineered yet. See `rsmm.engine.savefile`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.cli import _term
from rsmm.engine import savefile
from rsmm.engine.paths import DEFAULT_GAME_DIR


def _resolve(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths]
    found = savefile.find_saves(DEFAULT_GAME_DIR)
    if not found:
        sys.exit(f"no Profile_*.ob under {DEFAULT_GAME_DIR}/_Save (pass a path)")
    return found


def _report(path: Path, s: savefile.Save, st: _term.Style, show_all: bool) -> None:
    print(_term.rule(path.name, st))
    print(f"  {st.dim('path')}      {path}")

    opaque = len(s.data) - s.data_start
    frac = opaque / len(s.data) if s.data else 0.0

    if s.crc_ok:
        checksum = f"{st.ok('ok')} {st.dim(f'0x{s.stored_crc:08x}')}"
    else:
        checksum = (
            f"{st.err('MISMATCH')} "
            f"{st.dim(f'stored 0x{s.stored_crc:08x} / computed 0x{s.computed_crc:08x}')}"
        )

    print(f"  {st.dim('format')}    v{s.format_version}"
          f"   {st.dim('size')} {_term.human_bytes(len(s.data))}"
          f"   {st.dim('classes')} {len(s.classes)}")
    print(f"  {st.dim('checksum')}  {checksum}")
    # Bare bar reads as broken at these ratios (the registry is ~2% of the
    # file), so state the number too.
    decoded_pct = (1.0 - frac) * 100.0
    print(f"  {st.dim('decoded')}   {_term.bar(1.0 - frac, 20, st)} "
          f"{decoded_pct:.0f}%  "
          f"{st.dim(f'registry {s.data_start} B · {opaque} B opaque')}")

    rows = s.classes if show_all else [c for c in s.classes if c.version > 1]
    if not rows:
        return
    print()
    label = "class registry" if show_all else "classes above schema v1"
    print(f"  {st.bold(label)} {st.dim(f'({len(rows)})')}")

    name_w = min(max((len(c.name) for c in rows), default=10), 46)
    peak = max((c.version for c in rows), default=0)
    for c in sorted(rows, key=lambda c: (-c.version, c.name)):
        # The schema version is the only varying signal in the registry: a
        # high number means that class has been revised many times, which is
        # where format drift (and decoding risk) concentrates.
        if c.version <= 1:
            ver = st.dim(f"v{c.version:<3}")
        elif peak and c.version >= peak * 0.5:
            ver = st.accent(f"v{c.version:<3}")
        else:
            ver = f"v{c.version:<3}"
        print(f"    {c.name[:name_w]:<{name_w}}  {ver}  "
              f"{st.dim(f'hash 0x{c.hash:08x}')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm save", description=__doc__)
    ap.add_argument("paths", nargs="*", help="save files (default: autodetect)")
    ap.add_argument("--classes", action="store_true", help="list the full class registry")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    a = ap.parse_args(argv)

    st = _term.Style(enabled=False) if a.no_color else _term.Style()
    rc = 0
    targets = _resolve(a.paths)
    for i, path in enumerate(targets):
        if i:
            print()
        try:
            s = savefile.load(path)
        except (savefile.SaveFormatError, OSError) as e:
            print(f"{st.err('error')}  {path.name}: {e}")
            rc = 1
            continue
        if not s.crc_ok:
            rc = 1
        _report(path, s, st, a.classes)

    if len(targets) > 1:
        print()
        print(st.dim(f"{len(targets)} save(s) inspected"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
