#!/usr/bin/env python3
"""
Walk data/uncooked/, find every .gen file, write a sibling .gen.txt with
the ot_decoder structural dump.

Per-class body schemas live inside Ravenswatch.exe and aren't part of the
manager; the dump is structural-only (header + class table + section
ranges + embedded strings). Enough to read what each cooked file points
at, which is what a dev exploring the asset tree actually wants.
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rsmm.engine import ot_decoder  # noqa: E402


def decode_one(path: str):
    try:
        data = open(path, "rb").read()
        c = ot_decoder.Cursor(data)
        cf = ot_decoder.parse_header(c)
        ot_decoder.parse_class_table(c, cf)
        ot_decoder.parse_sections(c, cf)
        out = ot_decoder.emit(cf, path, show_raw=False)
        Path(path + ".txt").write_text(out)
        return ("ok", path)
    except Exception as e:
        return ("err", f"{path}: {type(e).__name__} {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/uncooked")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    targets = []
    for r, _, files in os.walk(args.root):
        for f in files:
            if f.endswith(".gen"):
                targets.append(os.path.join(r, f))
                if args.limit and len(targets) >= args.limit:
                    break
        if args.limit and len(targets) >= args.limit:
            break

    print(f"decoding {len(targets)} .gen files with {args.jobs} workers...", flush=True)
    ok = err = 0
    errs = []
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for i, fut in enumerate(as_completed(ex.submit(decode_one, p) for p in targets), 1):
            tag, info = fut.result()
            if tag == "ok":
                ok += 1
            else:
                err += 1
                if len(errs) < 20:
                    errs.append(info)
            if i % 2000 == 0:
                print(f"  {i}/{len(targets)} ok={ok} err={err}", flush=True)
    print(f"done: ok={ok} err={err}")
    if errs:
        print("first errors:")
        for e in errs[:10]:
            print("  " + e)


if __name__ == "__main__":
    main()
