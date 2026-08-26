#!/usr/bin/env bash
# Publish release notes to the rolling `changelog` GitHub release.
#
# The desktop app's "What's new" dialog reads this asset, so a note reaches
# every installed client on its next check with no app release in between.
# That is the whole point of the channel: the loader DLL and Lua SDK already
# update out of band (scripts/publish_loader.sh), and before this there was
# no way to tell anyone what those updates changed.
#
# Source of truth is data/changelog.json — the same file bundled into the
# sidecar as the offline fallback, so the shipped copy and the published one
# cannot drift.
#
# Usage:
#   $EDITOR data/changelog.json      # add an entry at the TOP of "entries"
#   scripts/publish_changelog.sh
#
# Unsigned by design: this payload is display text, never code, and is never
# written anywhere the game or the loader reads. rsmm.engine.changelog_feed
# treats it as untrusted input and bounds every field.
set -euo pipefail

cd "$(dirname "$0")/.."

TAG=changelog
FEED=data/changelog.json

[ -f "$FEED" ] || { echo "missing $FEED" >&2; exit 1; }

# Validate through the exact parser the clients use, so a payload that would
# be dropped or truncated on a user's machine is rejected here instead.
python3 - "$FEED" <<'EOF'
import json, sys
sys.path.insert(0, "src")
from rsmm.engine.changelog_feed import ChangelogError, parse

raw = open(sys.argv[1], "rb").read()
try:
    feed = parse(raw)
except ChangelogError as e:
    sys.exit(f"refusing to publish: {e}")

source = json.loads(raw.decode("utf-8"))
# The parser silently drops what it cannot use. That is right on a user's
# machine and wrong here: a dropped entry means a note nobody will ever see.
dropped = len(source.get("entries", [])) - len(feed["entries"])
if dropped:
    sys.exit(f"refusing to publish: {dropped} entry/entries would be dropped "
             "as unusable (needs a non-empty version and at least one highlight)")

# Identity, not `version` alone. A loader-channel entry carries an EMPTY
# version and identifies by loader_version, so keying the dedup on `version`
# made every channel entry collide with every other one — the feed could hold
# exactly one loader note, and adding a second refused the whole publish. That
# stayed invisible while loader v8 was the only channel entry and bit on v9.
def _key(e):
    return f"v{e['version']}" if e.get("version") else f"loader:{e.get('loader_version')}"

seen = set()
for e in feed["entries"]:
    k = _key(e)
    if k in seen:
        sys.exit(f"refusing to publish: duplicate entry {k}")
    seen.add(k)
    if not e.get("date"):
        sys.exit(f"refusing to publish: {k} has no date")

newest = feed["entries"][0]
# A loader-channel note has no app version to print; name the loader build.
label = (f"v{newest['version']}" if newest.get("version")
         else f"loader v{newest.get('loader_version')}")
print(f"ok: {len(feed['entries'])} entries, newest {label} "
      f"({newest['date']}), generated {feed['generated'] or 'unstamped'}")
EOF

if ! gh release view "$TAG" >/dev/null 2>&1; then
    gh release create "$TAG" --title "Changelog (rolling)" --notes \
        "Rolling release-notes feed consumed by the desktop app's \"What's new\" dialog and by \`rsmm changelog\`. The asset is replaced in place; do not pin." \
        --latest=false
fi
gh release upload "$TAG" "$FEED" --clobber
echo "published $FEED to release '$TAG'"
