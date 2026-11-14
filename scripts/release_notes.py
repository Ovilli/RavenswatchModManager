#!/usr/bin/env python3
"""The GitHub release body for a ``v*`` tag, written from git and the feed.

    python scripts/release_notes.py v5.9.32                 print it
    python scripts/release_notes.py v5.9.32 -o notes.md     write it
    python scripts/release_notes.py v5.9.32 --repo O/R      link commits there
    python scripts/release_notes.py channel loader --version 60 --since <sha> \
        [--until <sha>] [--notes TEXT] [--existing old.md] -o new.md

The body holds:

* the release note ``data/changelog.json`` carries for that version (its
  summary and highlights: the same text the app's "What's new" shows);
* every change since the previous release tag: each pull request (merged or
  squashed) and each direct commit on main, with its title, short hash and
  author, newest first;
* who contributed, and a compare link.

``channel loader|cli`` writes the body of a rolling channel release (the
signed loader + Lua SDK, the frozen CLI). Its assets are replaced in place, and
its body used to be one fixed sentence that never said what a publish changed.
Each publish now adds a section on top: its channel version, its notes, and
the commits since the previous publish's ``built_from`` that touch that
component (``CHANNEL_PATHS``). The last ``CHANNEL_KEEP`` sections stay below.

Releases used to say only "RSMM vX — see commit log for changes." The
previous tag is the newest ``v<semver>`` tag that is an ancestor of this one,
so a re-tag or an out-of-order tag still lists exactly what it adds.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
#: Commits that are the release machinery, not a change: the bump itself and
#: the channel publish stamps.
_MACHINERY = re.compile(r"^chore\((release|loader|cli|changelog|patterns)\): "
                        r"(bump to|publish)")
_MERGE = re.compile(r"^Merge pull request #(\d+) from \S+")
_SQUASH = re.compile(r"\(#(\d+)\)\s*$")


#: What each rolling channel ships, by the paths whose commits it lists.
CHANNEL_PATHS = {
    "loader": ["src/loader", "data/symbols.json", "data/loader_version.json"],
    "cli": ["src/rsmm", "pyproject.toml", "data", "scripts/build-sidecar.py"],
}
CHANNEL_INTRO = {
    "loader": "Rolling, signed loader DLL + Lua SDK bundle consumed by `rsmm update-loader`. "
              "Assets are replaced in place; do not pin.",
    "cli": "Rolling, signed frozen CLI consumed by the desktop app (`rsmm json update-cli`). "
           "Assets are replaced in place; do not pin.",
}
#: Publishes a channel body keeps (newest first).
CHANNEL_KEEP = 15
_SECTION = "\n## "


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout


def _version(tag: str) -> tuple[int, int, int] | None:
    m = _SEMVER.match(tag)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def previous_tag(tag: str) -> str | None:
    """The newest release tag below ``tag`` that is an ancestor of it."""
    me = _version(tag)
    if me is None:
        raise SystemExit(f"{tag!r} is not a v<major>.<minor>.<patch> tag")
    older = []
    for t in git("tag", "--merged", f"{tag}^", "--list", "v*").split():
        v = _version(t)
        if v is not None and v < me:
            older.append((v, t))
    return max(older)[1] if older else None


def changes(prev: str | None, tag: str, paths: list[str] | None = None) -> list[dict]:
    """Each first-parent commit in ``prev..tag``: a PR (merge or squash) or a
    direct commit, newest first. Merge commits take the PR's title from their
    body, as GitHub writes it."""
    span = f"{prev}..{tag}" if prev else tag
    out = []
    raw = git("log", "--first-parent", "--format=%H%x1f%an%x1f%s%x1f%b%x1e", span,
              *(["--", *paths] if paths else []))
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, author, subject, body = [*rec.split("\x1f"), "", "", "", ""][:4]
        if _MACHINERY.match(subject):
            continue
        pr = None
        title = subject
        m = _MERGE.match(subject)
        if m:
            pr = int(m[1])
            title = next((ln.strip() for ln in body.splitlines() if ln.strip()), subject)
        else:
            m = _SQUASH.search(subject)
            if m:
                pr = int(m[1])
                title = _SQUASH.sub("", subject).rstrip()
        out.append({"sha": sha, "author": author, "title": title, "pr": pr})
    return out


def feed_entry(version: str) -> dict | None:
    feed = json.loads((ROOT / "data" / "changelog.json").read_text(encoding="utf-8"))
    entries = feed.get("entries", []) if isinstance(feed, dict) else feed
    return next((e for e in entries if e.get("version") == version), None)


def render(tag: str, repo: str) -> str:
    version = tag.removeprefix("v")
    prev = previous_tag(tag)
    items = changes(prev, tag)
    lines: list[str] = []
    note = feed_entry(version)
    if note:
        lines.append(note.get("summary", "").strip())
        lines.append("")
        for h in note.get("highlights") or []:
            lines.append(f"- {h}")
        lines.append("")
    url = f"https://github.com/{repo}"
    prs = [c for c in items if c["pr"]]
    direct = [c for c in items if not c["pr"]]
    if prs:
        lines += ["## Pull requests", "", *_change_lines(prs, url), ""]
    if direct:
        lines += ["## Commits", "", *_change_lines(direct, url), ""]
    if not items:
        lines.append("No code changes since the previous release.")
        lines.append("")
    authors = sorted({c["author"] for c in items}, key=str.lower)
    if authors:
        lines.append(f"**Contributors:** {', '.join(authors)}")
        lines.append("")
    if prev:
        lines.append(f"**Full changes:** {url}/compare/{prev}...{tag}")
    return "\n".join(lines).rstrip() + "\n"


def _change_lines(items: list[dict], url: str) -> list[str]:
    out = []
    for c in items:
        ref = f"#{c['pr']}, " if c["pr"] else ""
        out.append(f"- {c['title']} ({ref}[`{c['sha'][:8]}`]({url}/commit/{c['sha']})) "
                   f"by {c['author']}")
    return out


def render_channel(channel: str, version: int, since: str | None, until: str, notes: str,
                   existing: str, repo: str, date: str) -> str:
    """A rolling channel release's body: this publish's section on top of the
    previous ones (the intro line, then at most CHANNEL_KEEP sections)."""
    url = f"https://github.com/{repo}"
    items = changes(since, until, CHANNEL_PATHS[channel])
    sec = [f"## {channel} v{version} ({date})", ""]
    if notes.strip():
        sec += [notes.strip(), ""]
    sec += [f"Built from [`{until[:8]}`]({url}/commit/{until})"
            + (f"; changes since [`{since[:8]}`]({url}/compare/{since}...{until}):"
               if since else ":"), ""]
    sec += _change_lines(items, url) or ["- No changes to this component."]
    old = existing.split(_SECTION)[1:] if _SECTION in existing else []
    old = [o for o in old if not o.startswith(f"{channel} v{version} ")][:CHANNEL_KEEP - 1]
    body = [CHANNEL_INTRO[channel], "\n".join(sec)]
    body += ["## " + o.strip() for o in old]
    return "\n\n".join(b.rstrip() for b in body).rstrip() + "\n"


def _repo() -> str:
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", git("remote", "get-url", "origin").strip())
    return m[1] if m else "Ovilli/RavenswatchModManager"


def main_channel(argv: list[str]) -> int:
    import datetime
    ap = argparse.ArgumentParser(prog="release_notes.py channel")
    ap.add_argument("channel", choices=sorted(CHANNEL_PATHS))
    ap.add_argument("--version", type=int, required=True, help="the channel version published")
    ap.add_argument("--since", help="the previous publish's built_from commit")
    ap.add_argument("--until", default="HEAD", help="the commit this publish was built from")
    ap.add_argument("--notes", default="", help="what the publisher said about it")
    ap.add_argument("--existing", type=Path, help="the release's current body, kept below")
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--repo")
    a = ap.parse_args(argv)
    since = a.since
    if since and subprocess.run(["git", "cat-file", "-e", f"{since}^{{commit}}"], cwd=ROOT,
                                capture_output=True).returncode != 0:
        since = None                    # a stamp from a commit this clone lacks
    until = git("rev-parse", a.until).strip()
    existing = a.existing.read_text(encoding="utf-8") if a.existing and a.existing.is_file() else ""
    body = render_channel(a.channel, a.version, since, until, a.notes, existing,
                          a.repo or _repo(), datetime.date.today().isoformat())
    if a.output:
        a.output.write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "channel":
        return main_channel(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tag", help="the release tag, e.g. v5.9.32")
    ap.add_argument("-o", "--output", type=Path, help="write the body here instead of stdout")
    ap.add_argument("--repo", help="owner/name the commit links point at (default: origin)")
    args = ap.parse_args(argv)
    body = render(args.tag, args.repo or _repo())
    if args.output:
        args.output.write_text(body, encoding="utf-8")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
