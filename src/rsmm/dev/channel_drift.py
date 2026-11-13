"""Has `main` drifted past what the published channels ship?

The loader channel (DLL + Lua SDK) and the CLI channel (frozen Python CLI) are
published by hand-dispatched workflows that commit a stamp bump
(`data/loader_version.json`, `data/cli_version.json`). Anything merged after
that commit, under a path the channel ships, is not in the channel yet, so
testers on the published build do not have it.

This module finds the last commit that touched each stamp and lists the later
commits that touched the channel's paths. Stdlib only, always exits 0.

    python -m rsmm.dev.channel_drift              # plain text
    python -m rsmm.dev.channel_drift --json
    python -m rsmm.dev.channel_drift --markdown   # CI step summary
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

#: The one place that says what each channel ships.
#: loader: scripts/publish_loader.sh packs the DLL and the Lua SDK, both under
#:   src/loader.
#: cli: scripts/build-sidecar.py freezes src/rsmm plus the data files its
#:   BUNDLE lists that change by hand (the asset map). The stamps and
#:   data/changelog.json are left out on purpose: the publish bots write them,
#:   so listing them would make every publish look like drift on the other
#:   channel.
CHANNELS: dict[str, dict] = {
    "loader": {
        "label": "Loader",
        "stamp": "data/loader_version.json",
        "key": "loader_version",
        "paths": ["src/loader"],
    },
    "cli": {
        "label": "CLI",
        "stamp": "data/cli_version.json",
        "key": "cli_version",
        "paths": ["src/rsmm", "data/asset_map.json", "data/asset_map.csv"],
    },
}

#: Subjects listed per channel in the text and Markdown reports.
SHOW = 8


def _git(repo: Path, *args: str) -> str | None:
    try:
        p = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def is_shallow(repo: Path) -> bool:
    return (repo / ".git" / "shallow").exists()


def _version(repo: Path, stamp: str, key: str) -> int | None:
    try:
        v = json.loads((repo / stamp).read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError):
        return None
    return v if isinstance(v, int) else None


def channel_state(repo: Path, name: str) -> dict:
    """One channel's drift: status is `current`, `behind` or `unknown`."""
    spec = CHANNELS[name]
    out: dict = {
        "channel": name,
        "label": spec["label"],
        "paths": list(spec["paths"]),
        "status": "unknown",
        "reason": "",
        "version": _version(repo, spec["stamp"], spec["key"]),
        "published_commit": None,
        "count": 0,
        "commits": [],
    }
    if is_shallow(repo):
        out["reason"] = "shallow clone"
        return out
    last = (_git(repo, "log", "-1", "--format=%H", "--", spec["stamp"]) or "").strip()
    if not last:
        out["reason"] = "no publish commit found"
        return out
    out["published_commit"] = last[:10]
    log = _git(repo, "log", "--format=%h %s", f"{last}..HEAD", "--", *spec["paths"])
    if log is None:
        out["reason"] = "git log failed"
        return out
    lines = [ln for ln in log.splitlines() if ln.strip()]
    out["count"] = len(lines)
    out["commits"] = lines
    out["status"] = "behind" if lines else "current"
    return out


def drift(repo: Path) -> list[dict]:
    return [channel_state(repo, n) for n in CHANNELS]


def summary_line(c: dict) -> str:
    v = f" v{c['version']}" if c["version"] is not None else ""
    head = f"{c['label']} channel{v}"
    if c["status"] == "current":
        return f"{head} matches main"
    if c["status"] == "behind":
        n = c["count"]
        paths = ", ".join(c["paths"])
        return f"{head} is {n} commit{'s' if n != 1 else ''} behind main ({paths})"
    return f"{head}: unknown ({c['reason']})"


def render_text(states: list[dict]) -> str:
    lines: list[str] = []
    for c in states:
        lines.append(summary_line(c))
        for ln in c["commits"][:SHOW]:
            lines.append(f"  {ln}")
        if c["count"] > SHOW:
            lines.append(f"  ... and {c['count'] - SHOW} more")
    return "\n".join(lines)


def render_markdown(states: list[dict]) -> str:
    out = ["## Published channels vs main", ""]
    for c in states:
        out.append(f"**{summary_line(c)}**")
        if c["commits"]:
            out.append("")
            for ln in c["commits"][:SHOW]:
                sha, _, subj = ln.partition(" ")
                out.append(f"- `{sha}` {subj}")
            if c["count"] > SHOW:
                out.append(f"- ... and {c['count'] - SHOW} more")
        out.append("")
    out.append("A channel that is behind needs a publish before testers get "
               "those changes.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="channel_drift",
        description="Report commits on this checkout not yet in the "
                    "published loader / CLI channels (always exits 0)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--markdown", action="store_true",
                    help="Markdown section (for $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--repo", type=Path,
                    default=Path(__file__).resolve().parents[3],
                    help="git checkout to inspect (default: this one)")
    args = ap.parse_args(argv)
    try:
        states = drift(args.repo)
    except Exception as e:  # noqa: BLE001 - informational, must never fail a job
        print(f"channel drift unknown ({type(e).__name__}: {e})", file=sys.stderr)
        return 0
    if args.json:
        print(json.dumps({"channels": states}, indent=2))
    elif args.markdown:
        print(render_markdown(states), end="")
    else:
        print(render_text(states))
    return 0


if __name__ == "__main__":
    sys.exit(main())
