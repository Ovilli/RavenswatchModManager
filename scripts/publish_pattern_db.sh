#!/usr/bin/env bash
# Publish the regenerated pattern DB as a rolling GitHub release asset.
#
# data/function_patterns.json is gitignored (14MB, game-derived bytes), so
# it cannot ride the repo. Instead it ships as assets on a rolling release
# tagged `pattern-db`, which `rsmm update-data` on user machines polls and
# plants into <game>/rsmm/data/ — no app release needed after a game patch.
#
# Workflow after a game update:
#   python scripts/gen_function_patterns.py   # regenerates DB + meta stamp
#   scripts/publish_pattern_db.sh             # pushes both to the tag
set -euo pipefail

cd "$(dirname "$0")/.."

TAG=pattern-db
DB=data/function_patterns.json
META=data/function_patterns.meta.json
# Content fingerprints (data/symbol_fingerprints.json) ride along. They are NOT
# consumed by the game or by `rsmm update-data` — they are the DEV artifact that
# makes the next game patch cheap: remap Pass 3 relocates a symbol by what it
# CONTAINS (constants, string refs, named callers/callees) after its prologue
# bytes have shifted, which is the failure the pattern DB cannot survive.
#
# They were tracked in git exactly once (e3b150b) and then stripped, correctly:
# they carry strings lifted out of the shipped exe, and game bytes do not go in
# the repo. Stripping them left them machine-local, though, so the artifact
# designed to outlive a game patch could not outlive a laptop. This channel
# already ships 20MB of game-derived byte patterns, so it is the right home.
FPS=data/symbol_fingerprints.json

[ -f "$DB" ] || { echo "missing $DB — run scripts/gen_function_patterns.py first" >&2; exit 1; }
[ -f "$META" ] || { echo "missing $META — regen with the updated gen script (it stamps the meta)" >&2; exit 1; }

# Sanity: every symbol's semantic pattern entry must be present — shipped
# loader DLLs resolve by these stable names (see sync_symbol_patterns.py).
python3 - <<'EOF'
import json, sys
sys.path.insert(0, "src")
from rsmm.engine.symbols import load_symbol_map
names = {e["name"] for e in json.load(open("data/function_patterns.json"))}
# Only status=ok symbols get semantic DB entries (sync_symbol_patterns.py
# skips the rest — their raw/anchor still points at a pre-patch address).
missing = [s.pattern_name for s in load_symbol_map().symbols
           if s.status == "ok" and s.pattern_name and s.pattern_name not in names]
if missing:
    sys.exit(f"{len(missing)} semantic entries missing from DB — run "
             f"scripts/sync_symbol_patterns.py first: {missing[:6]}")
print(f"ok: all semantic symbol entries present")
EOF

# Sanity: meta must describe exactly this DB file.
python3 - "$DB" "$META" <<'EOF'
import hashlib, json, sys
db, meta = sys.argv[1], sys.argv[2]
m = json.load(open(meta))
h = hashlib.sha256(open(db, "rb").read()).hexdigest()
if m.get("patterns_sha256") != h:
    sys.exit(f"meta patterns_sha256 does not match {db} — re-run gen_function_patterns.py")
print(f"ok: {m['pattern_count']} patterns, generated {m['generated']}, "
      f"game build {m['game_exe_sha256'][:12]}")
EOF

# Fingerprint coverage is the single best predictor of how expensive the next
# game patch will be, so report it at publish time rather than discovering it
# after the patch lands. Missing fingerprints are a warning, not a failure —
# publishing a good DB should never be blocked by an incomplete side artifact.
UPLOAD=("$DB" "$META")
if [ -f "$FPS" ]; then
    UPLOAD+=("$FPS")
    python3 - "$FPS" <<'EOF'
import json, sys
sys.path.insert(0, "src")
from rsmm.engine.symbols import load_symbol_map
fps = json.load(open(sys.argv[1]))
ok = [s.name for s in load_symbol_map().symbols
      if s.status == "ok" and s.kind in ("function", "event")]
missing = [n for n in ok if n not in fps]
print(f"ok: {len(fps)} fingerprints, covering {len(ok) - len(missing)}/{len(ok)} "
      f"ok symbols")
if missing:
    print(f"WARNING: {len(missing)} ok symbol(s) have NO fingerprint and will "
          f"strand on the next game patch — run tools/mine_fingerprints.py: "
          f"{missing[:6]}")
EOF
else
    echo "WARNING: $FPS missing — run tools/mine_fingerprints.py so symbols" \
         "survive the next game patch" >&2
fi

if ! gh release view "$TAG" >/dev/null 2>&1; then
    gh release create "$TAG" --title "Pattern DB (rolling)" --notes \
        "Rolling function-pattern database consumed by \`rsmm update-data\`. Assets are replaced in place after each game update; do not pin." \
        --latest=false
fi
gh release upload "$TAG" "${UPLOAD[@]}" --clobber
echo "published ${UPLOAD[*]} to release '$TAG'"
