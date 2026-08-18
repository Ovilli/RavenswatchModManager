#!/usr/bin/env bash
# Publish the loader DLL + Lua SDK as a signed, rolling GitHub release asset.
#
# Neither payload needs to ride inside the desktop bundle: winhttp.dll is a
# plain file in the game directory and the Lua SDK is disk-loaded from
# <game>/rsmm/lib/. Shipping them here means a Lua-only change costs a
# publish, not a desktop release plus a reinstall on every user's machine.
# `rsmm update-loader` consumes this; see src/rsmm/engine/loader_update.py.
#
# Workflow:
#   src/loader/build.sh                  # or build.bat — produce dist/winhttp.dll
#   scripts/publish_loader.sh --notes "what changed"
#   git commit data/loader_version.json  # the bump MUST be committed
#
# The bundled stamp in data/loader_version.json is what stops a
# `restore --all` + `install-loader` cycle from downgrading users, so the
# published version and the committed version have to stay in step.
set -euo pipefail

cd "$(dirname "$0")/.."

TAG=loader
ABI=1
NOTES=""
DRY_RUN=0
while [ $# -gt 0 ]; do
    case "$1" in
        --notes) NOTES="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        *) echo "usage: $0 [--notes <text>] [--dry-run]" >&2; exit 2 ;;
    esac
done

DLL=dist/winhttp.dll
[ -f "$DLL" ] || { echo "missing $DLL — build it first (src/loader/build.sh)" >&2; exit 1; }

# Same gates install-loader applies before planting, applied before publishing:
# this channel reaches users without a human running install-loader, so a
# broken payload here is not caught by anything downstream.
python3 scripts/validate_loader_dll.py "$DLL"

LUAC=""
for c in luac5.4 luac5.3 luac; do command -v "$c" >/dev/null && { LUAC="$c"; break; }; done
if [ -n "$LUAC" ]; then
    find src/loader/lib src/loader/lua -name '*.lua' -print0 \
        | xargs -0 -n1 "$LUAC" -p
    echo "ok: SDK Lua compiles ($LUAC)"
else
    echo "WARNING: no luac on PATH — publishing an SDK that was not compile-checked" >&2
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
PAYLOAD="$STAGE/payload"
mkdir -p "$PAYLOAD/lib"

cp "$DLL" "$PAYLOAD/winhttp.dll"
# Mirror exactly what install_loader.sh / .ps1 plant into <game>/rsmm/lib:
# the modular src/loader/lua tree, then the lib/ entrypoint + generated files
# on top (lib/rsmm.lua require-merges the former).
cp -a src/loader/lua/. "$PAYLOAD/lib/"
for f in rsmm.lua engine_gen.lua events_gen.lua; do
    [ -f "src/loader/lib/$f" ] && cp "src/loader/lib/$f" "$PAYLOAD/lib/$f"
done

BUNDLE="$STAGE/loader-bundle.tar.gz"
# Deterministic: sorted members, no mtimes/uids, so an unchanged payload
# produces an unchanged bundle hash.
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime='@0' \
    -czf "$BUNDLE" -C "$PAYLOAD" .

VERSION=$(python3 -c "import json;print(json.load(open('data/loader_version.json'))['loader_version'])")
NEXT=$((VERSION + 1))

python3 - "$PAYLOAD" "$BUNDLE" "$STAGE/loader.manifest.json" "$NEXT" "$ABI" "$NOTES" <<'PYEOF'
import hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

payload, bundle, out, version, abi, notes = sys.argv[1:7]
payload = Path(payload)

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

files = []
for p in sorted(payload.rglob("*")):
    if p.is_file():
        files.append({
            "path": p.relative_to(payload).as_posix(),
            "sha256": sha256(p),
            "size": p.stat().st_size,
        })

try:
    rsmm_version = json.load(open("apps/desktop/package.json"))["version"]
except (OSError, ValueError, KeyError):
    rsmm_version = None

manifest = {
    "abi": int(abi),
    "loader_version": int(version),
    "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "rsmm_version": rsmm_version,
    "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip() or None,
    "bundle_name": "loader-bundle.tar.gz",
    "bundle_sha256": sha256(bundle),
    "notes": notes or None,
    "files": files,
}
Path(out).write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
print(f"manifest: loader v{version}, abi {abi}, {len(files)} files, "
      f"bundle {manifest['bundle_sha256'][:12]}")
PYEOF

# --- sign ---------------------------------------------------------------
# Signed with the SAME minisign key that signs the desktop bundles; the
# matching pubkey is embedded in src/rsmm/engine/loader_update.py. The
# manifest hashes every payload file, so signing the manifest signs the
# whole bundle. Verification on the client is mandatory and fail-closed —
# an unsigned publish is a publish users will (correctly) refuse.
SIG="$STAGE/loader.manifest.json.minisig"
if [ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
    # Pass the secret through VERBATIM as an env var. Two traps here, both
    # verified against the real CLI: `tauri signer sign` reads TAURI_PRIVATE_KEY
    # (not TAURI_SIGNING_PRIVATE_KEY, which only `tauri build` honours), and the
    # key material is itself base64-wrapped — "helpfully" decoding it, or piping
    # it through a file, corrupts it. Env var also keeps it out of argv and off
    # disk. `pnpm tauri` exists only in the desktop workspace, not at the repo
    # root, so this runs through --filter; paths are absolute.
    env TAURI_PRIVATE_KEY="$TAURI_SIGNING_PRIVATE_KEY" \
        TAURI_PRIVATE_KEY_PASSWORD="${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" \
        pnpm --silent --filter desktop exec tauri signer sign \
        "$STAGE/loader.manifest.json"
    # tauri writes <file>.sig holding the whole minisign signature file wrapped
    # in ONE MORE layer of base64. Unwrap it so the published asset is plain
    # minisign text, checkable with a stock `minisign -V` and not only by us.
    if [ ! -f "$STAGE/loader.manifest.json.sig" ]; then
        echo "ERROR: tauri signer produced no .sig" >&2; exit 1
    fi
    if ! base64 -d < "$STAGE/loader.manifest.json.sig" > "$SIG" 2>/dev/null; then
        cp "$STAGE/loader.manifest.json.sig" "$SIG"   # already plain text
    fi
    head -1 "$SIG" | grep -q 'untrusted comment' || {
        echo "ERROR: signature is not in minisign format" >&2; exit 1; }
elif command -v minisign >/dev/null; then
    minisign -Sm "$STAGE/loader.manifest.json" -x "$SIG"
else
    echo "ERROR: no signing key. Set TAURI_SIGNING_PRIVATE_KEY (+ _PASSWORD)" >&2
    echo "       or install minisign. Clients refuse an unsigned manifest." >&2
    exit 1
fi
[ -s "$SIG" ] || { echo "ERROR: signing produced no signature" >&2; exit 1; }

# Verify with the client's own code path before anything is uploaded — the
# one check that proves users can actually install what is about to ship.
PYTHONPATH=src python3 - "$STAGE/loader.manifest.json" "$SIG" <<'PYEOF'
import json, sys
from rsmm.engine.loader_update import _validate_manifest, public_key, resolve_destination
from rsmm.engine.minisign import verify

manifest, sig = sys.argv[1], sys.argv[2]
raw = open(manifest, "rb").read()
tc = verify(raw, open(sig).read(), public_key())
print(f"ok: signature verifies against the shipped pubkey ({tc[:60]})")

# Run the CLIENT's own structural validation. The client refuses illegal
# member names, duplicate paths and destinations outside its allowlist —
# so a payload that trips any of those must be caught here, at publish
# time, not as a failed update on every user's machine.
data = json.loads(raw)
_validate_manifest(data)
for f in data["files"]:
    print(f"   {'/'.join(resolve_destination(f['path'])):40s} {f['size']:>9,} bytes")
print(f"ok: manifest accepted by the client validator ({len(data['files'])} files)")
PYEOF

if [ "$DRY_RUN" = 1 ]; then
    echo "dry run — not uploading. Artifacts in $STAGE"
    trap - EXIT
    exit 0
fi

if ! gh release view "$TAG" >/dev/null 2>&1; then
    gh release create "$TAG" --title "Loader + Lua SDK (rolling)" --notes \
        "Rolling, signed loader DLL + Lua SDK bundle consumed by \`rsmm update-loader\`. Assets are replaced in place; do not pin." \
        --latest=false
fi
gh release upload "$TAG" \
    "$BUNDLE" "$STAGE/loader.manifest.json" "$SIG" --clobber

python3 - "$NEXT" <<'PYEOF'
import json, sys
from pathlib import Path
p = Path("data/loader_version.json")
d = json.loads(p.read_text())
d["loader_version"] = int(sys.argv[1])
p.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8")
PYEOF

echo "published loader v$NEXT to release '$TAG'"
echo "NOW COMMIT data/loader_version.json — an uncommitted bump means the next"
echo "app build ships a stamp lower than the channel and users get replanted."
