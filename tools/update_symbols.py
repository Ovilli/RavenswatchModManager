#!/usr/bin/env python3
"""Helpers for updating the symbol map after a game patch (the `update-symbols` skill).

  preflight      is the install clean vanilla, is Ghidra holding the project lock,
                 does the pattern DB already match the installed exe
  snapshot       copy the exe + Steam manifest, list and hash every game file, and
                 record cooked class versions, into <out>/<exe-sha12>/
  audit          after `remap_symbols.py --update-symbols`: compare each remapped
                 function's body old vs new and flag the ones to check by hand
  callers        direct call/jmp sites of a function, each mapped to the function
                 that contains it (via .pdata)
  fields         struct displacement votes old -> new over a family of functions
                 that take the same object
  class-versions cooked class versions across _Cooking; --baseline diffs two scans

Game bytes never go in git: point --out at a folder outside the repo.
"""

from __future__ import annotations

import argparse
import bisect
import difflib
import hashlib
import json
import os
import re
import shutil
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import gen_function_patterns as gen  # noqa: E402

COOKING = "DarkTalesResources/_Cooking"
SYMBOLS_JSON = REPO / "data/symbols.json"
PATTERN_META = REPO / "data/function_patterns.meta.json"
BODY_CAP = 0x4000          # bytes disassembled per function at most
NO_PDATA_BODY = 0x400      # body length assumed for an address .pdata does not know
FIELD_DISP_MAX = 0x100000  # larger displacements are image RVAs, not struct fields


def _game_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    from rsmm.engine.paths import default_game_dir
    return default_game_dir()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- PE image

class Image:
    """An exe's .text and its .pdata function table."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.base, self.secs = gen.parse_pe(self.data)
        t = self.secs[0]
        self.text = self.data[t["raw_off"]:t["raw_off"] + t["raw_size"]]
        self.tva = self.base + t["rva"]
        self.fn = {int(f["addr"], 16): int(f["addr"], 16) + f["size"]
                   for f in gen.pdata_functions(self.data)}
        self.starts = sorted(self.fn)

    def containing(self, va: int) -> int | None:
        k = bisect.bisect_right(self.starts, va) - 1
        if k >= 0 and va < self.fn[self.starts[k]]:
            return self.starts[k]
        return None

    def body(self, va: int) -> bytes:
        end = self.fn.get(va, va + NO_PDATA_BODY)
        end = min(end, va + BODY_CAP)
        off = va - self.tva
        if not 0 <= off < len(self.text):
            return b""
        return self.text[off:off + (end - va)]


def _cs(detail: bool = False):
    try:
        import capstone
    except ImportError:
        sys.exit("capstone is required: pip install capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = detail
    return md


# ---------------------------------------------------------------- symbols

def function_addrs(doc: dict) -> dict[str, int]:
    """name -> function address, from each symbol's raw FUN_ (anchors: the parent)."""
    out: dict[str, int] = {}
    for s in doc["symbols"]:
        if s.get("kind") not in ("function", "event"):
            continue
        raw = s.get("raw") or (s.get("anchor") or {}).get("raw")
        if raw and raw.startswith("FUN_"):
            out[s["name"]] = int(raw[4:], 16)
    return out


def _load_symbols(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# ---------------------------------------------------------------- preflight

def preflight(game: Path, ghidra: Path | None = None) -> int:
    problems = 0
    cooking = game / COOKING
    state = cooking / ".rsmm_state.json"
    if state.is_file():
        active = json.loads(state.read_text(encoding="utf-8")).get("active") or {}
        print(f"state      active = {len(active)} entr{'y' if len(active) == 1 else 'ies'}")
        if active:
            problems += 1
            print("  STOP: mods are applied. If Steam patched over them, patched files are mixed "
                  "with mod files; sort that out before any restore/apply.")
    else:
        print("state      no .rsmm_state.json (never applied)")
    baks = list(cooking.rglob("*.rsmm.bak")) if cooking.is_dir() else []
    print(f"backups    {len(baks)} *.rsmm.bak")
    if baks:
        problems += 1
        print(f"  STOP: backups left in _Cooking (first: {baks[0]})")

    env = os.environ.get("RSMM_GHIDRA_PROJECT")
    project = ghidra or (Path(env) if env else None)
    locks = list(project.glob("*.lock*")) if project and project.is_dir() else []
    if project is None:
        print("ghidra     not checked (pass --ghidra-project or set RSMM_GHIDRA_PROJECT)")
    elif not project.is_dir():
        problems += 1
        print(f"ghidra     not found: {project}")
    else:
        lock = "LOCKED (" + locks[0].name + ")" if locks else "unlocked"
        print(f"ghidra     {project}: {lock}")
    if locks:
        problems += 1
        print("  STOP: stop the Ghidra GUI / tools/ghidra_mcp/serve.sh first.")

    exe = game / "Ravenswatch.exe"
    if exe.is_file():
        sha = _sha256(exe)
        built = ""
        if PATTERN_META.is_file():
            built = json.loads(PATTERN_META.read_text(encoding="utf-8")).get("game_exe_sha256", "")
        print(f"exe        {sha[:12]}  pattern DB built for {built[:12] or '?'}"
              f"  -> {'no patch' if sha == built else 'PATCHED'}")
    else:
        problems += 1
        print(f"exe        missing: {exe}")
    print("OK" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


# ---------------------------------------------------------------- snapshot

def _steam_manifest(game: Path) -> Path | None:
    steamapps = game.parent.parent
    for acf in steamapps.glob("appmanifest_*.acf"):
        text = acf.read_text(encoding="utf-8", errors="replace")
        if re.search(r'"installdir"\s+"' + re.escape(game.name) + '"', text):
            return acf
    return None


def _modded(game: Path) -> str:
    """Why the install is not vanilla, or "" when it is."""
    cooking = game / COOKING
    state = cooking / ".rsmm_state.json"
    if state.is_file() and json.loads(state.read_text(encoding="utf-8")).get("active"):
        return "mods are applied (.rsmm_state.json active)"
    if cooking.is_dir() and next(cooking.rglob("*.rsmm.bak"), None):
        return "*.rsmm.bak backups in _Cooking"
    return ""


def snapshot(game: Path, out: Path, versions: bool = True, allow_modded: bool = False) -> int:
    why = _modded(game)
    if why and not allow_modded:
        print(f"STOP: {why}; a snapshot of a modded install is not the vanilla build "
              "(--allow-modded to take it anyway)")
        return 1
    exe = game / "Ravenswatch.exe"
    sha = _sha256(exe)
    dest = out / sha[:12]
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, dest / f"Ravenswatch-{sha[:12]}.exe")
    acf = _steam_manifest(game)
    if acf:
        shutil.copy2(acf, dest / acf.name)
        m = re.search(r'"buildid"\s+"(\d+)"', acf.read_text(encoding="utf-8", errors="replace"))
        print(f"steam      {acf.name} buildid {m.group(1) if m else '?'}")
    else:
        print("steam      no appmanifest found next to the install")
    files = sorted(p for p in game.rglob("*") if p.is_file())
    with open(dest / "listing.tsv", "w", encoding="utf-8") as lst, \
         open(dest / "sha256sums.txt", "w", encoding="utf-8") as sums:
        for p in files:
            rel = p.relative_to(game).as_posix()
            lst.write(f"{rel}\t{p.stat().st_size}\n")
            sums.write(f"{_sha256(p)}  {rel}\n")
    print(f"files      {len(files)} listed and hashed")
    if versions:
        scan = class_versions(game)
        (dest / "class_versions.json").write_text(json.dumps(scan, indent=1, sort_keys=True))
        print(f"classes    {len(scan)} cooked classes")
    print(f"wrote      {dest}")
    return 0


# ---------------------------------------------------------------- audit

_HEX = re.compile(r"0x[0-9a-f]+")


def _norm(insn) -> str:
    """Mnemonic + operands with addresses that move between builds blanked."""
    ops = insn.op_str
    if (insn.mnemonic == "call" or insn.mnemonic.startswith("j")) and _HEX.fullmatch(ops):
        return insn.mnemonic + " T"
    ops = re.sub(r"rip [+-] 0x[0-9a-f]+", "rip+X", ops)
    return insn.mnemonic + " " + _HEX.sub(
        lambda m: "A" if 0x140000000 <= int(m.group(0), 16) < 0x150000000 else m.group(0), ops)


def _direct_calls(insns) -> list[int]:
    return [int(i.op_str, 16) for i in insns
            if i.mnemonic == "call" and _HEX.fullmatch(i.op_str)]


def audit_pairs(old: Image, new: Image, pairs: dict[str, tuple[int, int]]) -> list[dict]:
    md = _cs()
    addr_map = dict(pairs.values())
    rows = []
    for name, (oa, na) in sorted(pairs.items()):
        oi = list(md.disasm(old.body(oa), oa))
        ni = list(md.disasm(new.body(na), na))
        a, b = [_norm(i) for i in oi], [_norm(i) for i in ni]
        ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0
        nt = set(_direct_calls(ni))
        mapped = [addr_map[t] for t in _direct_calls(oi) if t in addr_map]
        rows.append({
            "name": name, "old": hex(oa), "new": hex(na), "ratio": round(ratio, 3),
            "insns": [len(a), len(b)], "old_is_start": oa in old.fn, "new_is_start": na in new.fn,
            "calls_agree": [sum(1 for t in mapped if t in nt), len(mapped)],
            "unmoved": oa == na,
        })
    return rows


def _flags(r: dict, threshold: float, patched: bool) -> list[str]:
    f = []
    if r["ratio"] < threshold:
        f.append(f"body {r['ratio']}")
    # Leaf functions have no unwind entry, so only a start that stopped being one counts.
    if r["old_is_start"] and not r["new_is_start"]:
        f.append("no longer a .pdata start")
    if r["calls_agree"][0] < r["calls_agree"][1]:
        f.append("callees {}/{}".format(*r["calls_agree"]))
    if r["unmoved"] and patched and r["ratio"] < 1:
        f.append("unmoved (remap did not match?)")
    return f


def audit(old_exe: Path, new_exe: Path, old_syms: Path, new_syms: Path,
          threshold: float, out: Path | None) -> int:
    old, new = Image(old_exe), Image(new_exe)
    o = function_addrs(_load_symbols(old_syms))
    n = function_addrs(_load_symbols(new_syms))
    pairs = {k: (o[k], n[k]) for k in o.keys() & n.keys()}
    rows = audit_pairs(old, new, pairs)
    patched = old.data != new.data
    flagged = [(r, _flags(r, threshold, patched)) for r in rows]
    flagged = [(r, f) for r, f in flagged if f]
    flagged.sort(key=lambda t: t[0]["ratio"])
    for r, f in flagged:
        print(f"{r['name']:45} {r['old']} -> {r['new']}  insns {r['insns'][0]}/{r['insns'][1]}  "
              f"{'; '.join(f)}")
    print(f"{len(rows)} audited, {len(flagged)} flagged (threshold {threshold})")
    if out:
        out.write_text(json.dumps(rows, indent=1))
    return 1 if flagged else 0


# ---------------------------------------------------------------- callers

def call_sites(img: Image, target: int) -> list[tuple[int, str]]:
    """Every E8 call / E9 jmp rel32 in .text whose target is `target`."""
    out = []
    for op, kind in ((0xE8, "call"), (0xE9, "jmp")):
        i = img.text.find(bytes([op]))
        while i >= 0:
            if i + 5 <= len(img.text):
                rel = struct.unpack_from("<i", img.text, i + 1)[0]
                if img.tva + i + 5 + rel == target:
                    out.append((img.tva + i, kind))
            i = img.text.find(bytes([op]), i + 1)
    return sorted(out)


def callers(exe: Path, syms: Path | None, targets: list[str]) -> int:
    img = Image(exe)
    names = function_addrs(_load_symbols(syms)) if syms else {}
    by_addr = {v: k for k, v in names.items()}
    for t in targets:
        if t in names:
            va = names[t]
        else:
            try:
                va = int(t, 16)
            except ValueError:
                print(f"{t}: unknown symbol (not in the symbol map, not a hex address)",
                      file=sys.stderr)
                return 1
        sites = call_sites(img, va)
        fns = sorted({img.containing(s) for s, _ in sites} - {None})
        print(f"{t} ({va:#x}): {len(sites)} site(s) in {len(fns)} function(s)")
        for s, kind in sites:
            fn = img.containing(s)
            label = by_addr.get(fn, "") if fn else "outside .pdata"
            print(f"  {kind:4} {s:#x}  in {fn:#x} {label}" if fn else f"  {kind:4} {s:#x}  {label}")
    return 0


# ---------------------------------------------------------------- fields

def _mem_tokens(md, img: Image, va: int):
    from capstone import x86
    res = []
    for i in md.disasm(img.body(va), va):
        key, mems = [i.mnemonic], []
        for o in i.operands:
            if o.type == x86.X86_OP_MEM:
                m = o.mem
                base = i.reg_name(m.base) if m.base else None
                if base in ("rip", "rsp", "rbp") or (base is None and not m.index):
                    key.append("M:" + str(base))
                    continue
                mems.append((base, m.disp))
                key.append("M:" + str(base) + ("+i" if m.index else ""))
            elif o.type == x86.X86_OP_REG:
                key.append("R:" + i.reg_name(o.reg))
            else:
                key.append("I")
        res.append((tuple(key), mems))
    return res


def field_votes(old: Image, new: Image, oa: int, na: int) -> dict[int, Counter]:
    """old displacement -> Counter(new displacement), from aligned instructions."""
    md = _cs(detail=True)
    ot, nt = _mem_tokens(md, old, oa), _mem_tokens(md, new, na)
    sm = difflib.SequenceMatcher(None, [t[0] for t in ot], [t[0] for t in nt], autojunk=False)
    votes: dict[int, Counter] = defaultdict(Counter)
    for tag, i1, i2, j1, _j2 in sm.get_opcodes():
        if tag != "equal":
            continue
        for k in range(i2 - i1):
            for (_ob, od), (_nb, nd) in zip(ot[i1 + k][1], nt[j1 + k][1], strict=False):
                if 0 <= od < FIELD_DISP_MAX and 0 <= nd < FIELD_DISP_MAX:
                    votes[od][nd] += 1
    return votes


def fields(old_exe: Path, new_exe: Path, old_syms: Path, new_syms: Path,
           families: list[str], show_all: bool) -> int:
    old, new = Image(old_exe), Image(new_exe)
    o = function_addrs(_load_symbols(old_syms))
    n = function_addrs(_load_symbols(new_syms))
    for fam in families:
        title, _, members = fam.partition("=")
        table: dict[int, Counter] = defaultdict(Counter)   # old disp -> new disp -> functions
        used = []
        for m in members.split(","):
            m = m.strip()
            if ":" in m:
                oa, na = (int(x, 16) for x in m.split(":"))
            elif m in o and m in n:
                oa, na = o[m], n[m]
            else:
                print(f"  skip {m}: not a function symbol in both maps")
                continue
            used.append(m)
            for od, c in field_votes(old, new, oa, na).items():
                table[od][c.most_common(1)[0][0]] += 1
        print(f"== {title}: {len(used)} function(s)")
        deltas: Counter = Counter()
        for od in sorted(table):
            c = table[od]
            nd, votes = c.most_common(1)[0]
            split = len(c) > 1
            if nd != od:
                deltas[nd - od] += 1
            if nd != od or split or show_all:
                alt = ""
                if split:
                    alt = "  (split: " + ", ".join(f"{d:#x}x{v}" for d, v in c.most_common()) + ")"
                print(f"  {od:#07x} -> {nd:#07x}  {nd - od:+#x}  {votes} fn{alt}")
        moved = sum(deltas.values())
        summary = ", ".join(f"{d:+#x} x{k}" for d, k in deltas.most_common())
        print(f"  {len(table)} displacements, {len(table) - moved} unchanged, {moved} moved"
              + (": " + summary if summary else ""))
    return 0


# ---------------------------------------------------------------- class versions

def class_versions(game: Path) -> dict[str, list[str]]:
    from rsmm.engine import cooked
    seen: dict[str, set[str]] = defaultdict(set)
    for p in (game / COOKING).rglob("*"):
        if not p.is_file() or p.name.startswith(".") or p.suffix == ".bak":
            continue
        try:
            cf = cooked.parse(p.read_bytes())
        except Exception:  # noqa: BLE001 - not every file in _Cooking is a container
            continue
        for c in cf.classes:
            seen[c.name].add(f"{c.version_major}.{c.version_minor}")
    return {k: sorted(v) for k, v in seen.items()}


def class_versions_cmd(game: Path, out: Path | None, baseline: Path | None) -> int:
    scan = class_versions(game)
    if out:
        out.write_text(json.dumps(scan, indent=1, sort_keys=True))
    print(f"{len(scan)} cooked classes")
    if not baseline:
        return 0
    base = json.loads(baseline.read_text(encoding="utf-8"))
    changed = 0
    for name in sorted(base.keys() | scan.keys()):
        a, b = base.get(name), scan.get(name)
        if a != b:
            changed += 1
            print(f"  {name}: {a or 'absent'} -> {b or 'absent'}")
    print(f"{changed} class(es) changed version since {baseline}")
    return 1 if changed else 0


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preflight", help="clean install, Ghidra lock, patched or not")
    p.add_argument("--game")
    p.add_argument("--ghidra-project", type=Path,
                   help="folder holding the .gpr (default: $RSMM_GHIDRA_PROJECT)")

    p = sub.add_parser("snapshot", help="copy exe + acf, list/hash files, class versions")
    p.add_argument("--game")
    p.add_argument("--out", type=Path, required=True, help="folder OUTSIDE the repo")
    p.add_argument("--no-class-versions", action="store_true")
    p.add_argument("--allow-modded", action="store_true")

    def two_builds(p):
        p.add_argument("--old-exe", type=Path, required=True)
        p.add_argument("--new-exe", type=Path, required=True)
        p.add_argument("--old-symbols", type=Path, required=True,
                       help="symbols.json before the remap (git show <base>:data/symbols.json)")
        p.add_argument("--new-symbols", type=Path, default=SYMBOLS_JSON)

    p = sub.add_parser("audit", help="flag remapped functions whose body changed")
    two_builds(p)
    p.add_argument("--threshold", type=float, default=0.97)
    p.add_argument("--json", type=Path, help="write every row here")

    p = sub.add_parser("callers", help="call/jmp sites of a function, and their functions")
    p.add_argument("--exe", type=Path, required=True)
    p.add_argument("--symbols", type=Path, help="symbols.json for the same build (names)")
    p.add_argument("target", nargs="+", help="symbol name or hex VA")

    p = sub.add_parser("fields", help="struct displacement votes per family")
    two_builds(p)
    p.add_argument("--family", action="append", required=True,
                   help="Title=Sym1,Sym2,0xOLD:0xNEW,...  (functions taking the same object)")
    p.add_argument("--all", action="store_true", help="also print unchanged displacements")

    p = sub.add_parser("class-versions", help="cooked class versions; diff with --baseline")
    p.add_argument("--game")
    p.add_argument("--out", type=Path)
    p.add_argument("--baseline", type=Path, help="class_versions.json from the previous snapshot")

    a = ap.parse_args(argv)
    if a.cmd == "preflight":
        return preflight(_game_dir(a.game), a.ghidra_project)
    if a.cmd == "snapshot":
        return snapshot(_game_dir(a.game), a.out, not a.no_class_versions, a.allow_modded)
    if a.cmd == "audit":
        return audit(a.old_exe, a.new_exe, a.old_symbols, a.new_symbols, a.threshold, a.json)
    if a.cmd == "callers":
        return callers(a.exe, a.symbols, a.target)
    if a.cmd == "fields":
        return fields(a.old_exe, a.new_exe, a.old_symbols, a.new_symbols, a.family, a.all)
    if a.cmd == "class-versions":
        return class_versions_cmd(_game_dir(a.game), a.out, a.baseline)
    return 2


if __name__ == "__main__":
    sys.exit(main())
