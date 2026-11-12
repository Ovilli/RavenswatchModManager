"""Read the specific life-bar entity captured by the installed diagnostic.

Development tool only. Requests process query/read rights; never writes game
memory, calls game functions, injects code, or scans the process heap.
"""
import argparse
import hashlib
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import re

EXPECTED_EXE = "b9c3642884a8f3a463782f36c9a3a62bc14c88105315220c733fe6c2229ba904"
k = C.WinDLL("kernel32", use_last_error=True)
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.OpenProcess.restype = W.HANDLE
k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k.ReadProcessMemory.restype = W.BOOL
k.CloseHandle.argtypes = [W.HANDLE]
k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
k.QueryFullProcessImageNameW.restype = W.BOOL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    game = args.game_dir.resolve()
    if args.output.exists():
        raise SystemExit("Output already exists; choose a new capture filename.")
    if hashlib.sha256((game / "Ravenswatch.exe").read_bytes()).hexdigest() != EXPECTED_EXE:
        raise SystemExit("Unsupported game build; revalidate the structure before using this probe.")
    log = (game / "mods/_log.txt").read_text(encoding="utf-8", errors="replace")
    matches = list(re.finditer(r"\[[^\]]+ ([0-9]+)\].*component=([0-9a-f]+) oCEntityCpntEntitySpawner \| Life Bar Spawner", log))
    if not matches:
        raise SystemExit("No captured life-bar spawner in the current log.")
    hit = matches[-1]
    process_id, spawner = int(hit[1]), int(hit[2], 16)
    handle = k.OpenProcess(0x1000 | 0x10, False, process_id)
    if not handle:
        raise C.WinError(C.get_last_error())
    try:
        path, size = C.create_unicode_buffer(32768), W.DWORD(32768)
        if not k.QueryFullProcessImageNameW(handle, 0, path, C.byref(size)):
            raise C.WinError(C.get_last_error())
        if Path(path.value).resolve() != (game / "Ravenswatch.exe").resolve():
            raise SystemExit("Captured PID is no longer the expected game.")
        def read(p, size):
            if not isinstance(p, int) or p < 0x10000 or p >= 0x800000000000 or size > 4096:
                return None
            buf, got = C.create_string_buffer(size), C.c_size_t()
            if not k.ReadProcessMemory(handle, p, buf, size, C.byref(got)) or got.value != size:
                return None
            return buf.raw
        def num(p, n=8):
            raw = read(p, n)
            return int.from_bytes(raw, "little") if raw is not None else 0
        def text(p):
            raw = read(p, 160)
            return raw.split(b"\0", 1)[0].decode("utf-8", "replace") if raw else None
        def info(p):
            vft = num(p)
            col = num(vft - 8)
            if num(col, 4) != 1:
                return None
            base = col - num(col + 20, 4)
            name = text(base + num(col + 12, 4) + 16)
            if not name or not name.startswith(".?A"):
                return None
            return {"ptr": hex(p), "class": name, "vtable_rva": hex(vft-base), "base": hex(base)}
        parent = info(spawner)
        if not parent or parent["class"] != ".?AVoCEntityCpntEntitySpawner@@":
            raise SystemExit("Captured spawner is no longer live; no reads of its children.")
        entity = num(spawner + 0x88)
        obj = info(entity)
        if not obj or obj["class"] != ".?AVoCEntity@@":
            raise SystemExit("Life-bar entity is not live.")
        data, count = num(entity + 0x190), num(entity + 0x198, 4)
        if not 1 <= count <= 512:
            raise SystemExit("Implausible UI component count.")
        result = {"pid": process_id, "spawner": parent, "entity": obj, "components": []}
        for j in range(count):
            p = num(data + j * 8)
            component = info(p)
            if not component:
                continue
            component["name"] = text(num(num(p + 0x10) + 0xe8))
            name = (component["name"] or "").lower()
            if "GameUi@@" in component["class"] or "top bar" in name or "username" in name:
                component["links"] = []
                for off in range(0x68, 0x240, 8):
                    linked = info(num(p + off))
                    if linked:
                        linked["offset"] = hex(off)
                        component["links"].append(linked)
                print(component["name"], component["class"], component["ptr"])
                for linked in component["links"]:
                    if "oCUI" in linked["class"]:
                        print(" ", linked["offset"], linked["class"], linked["ptr"], "vtable", linked["vtable_rva"])
            result["components"].append(component)
        out = args.output
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("Saved", count, "component observations to", out)
    finally:
        k.CloseHandle(handle)


if __name__ == "__main__":
    main()
