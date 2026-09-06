"""rsmm exp — read back the hypotheses a mod answered during a playtest.

A playtest is the only source of truth for most of this SDK, and it is the
expensive step: a human plays the game, then a fresh session reads the log.
Historically one run returned ONE bit, because the answer was prose in
`_log.txt` that somebody had to interpret.

`R.exp` (src/loader/lua/rsmm/exp.lua) lets a mod declare several independent
hypotheses, record evidence under each, and close each with a verdict. The
verdicts land in the mod's own `R.kv` state file — the same store `rsmm
overlay` reads live HUD rows out of — and this command joins them back into a
table. One run, N answers.

Three states, and NO-DATA is a result too: a case that was declared and never
resolved says the code path never ran.

Two of the questions a playtest answers are not answerable from inside the
game, so this module carries the other half of the harness as well:

* a mod with no Lua at all (a texture override, a field patch) declares its
  questions in `manifest.toml` as `[[experiment]]` blocks, so they show up as
  NO-DATA before the run instead of living in a TOML comment nobody re-reads;
* a question whose answer is *on the screen* -- did the icon change, did the
  structure appear -- is closed by the player with `rsmm exp answer`, and the
  verdict is marked as human-reported so it is never confused with a measured
  one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from rsmm.cli import _term
from rsmm.cli.cmd_overlay import mods_dir, parse_kv, state_file

# The state file, its escaping and its NaN handling are already solved for the
# overlay reader; an `exp` case is just different keys in the same store.
_ST = _term.Style()

PREFIX = "exp."
#: Written once per process by the first R.exp call, after it drops the
#: previous launch's keys. Not a case.
SESSION_KEY = "exp._session"

PASS, FAIL, NODATA = "pass", "fail", "no-data"

#: Marks a verdict a person typed rather than one the game measured. The two
#: are different grades of evidence and the table says which is which.
BY_HUMAN = "you"

MAX_CASES = 32
MAX_TEXT = 200


class ExpError(ValueError):
    """A malformed `[[experiment]]` declaration."""


def parse_declarations(raw: Any, *, mod_id: str) -> list[dict[str, str]]:
    """Validate a manifest's `[[experiment]]` blocks.

    Checked here and called from `rsmm lint`, for the same reason the overlay
    spec is: a typo in a declaration would otherwise surface as a question
    silently missing from the table after the playtest that was supposed to
    answer it.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ExpError(f"{mod_id}: [[experiment]] must be a list of blocks")
    if len(raw) > MAX_CASES:
        raise ExpError(f"{mod_id}: too many [[experiment]] blocks (max {MAX_CASES})")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, block in enumerate(raw):
        if not isinstance(block, dict):
            raise ExpError(f"{mod_id}: [[experiment]] #{i + 1} is not a table")
        cid = str(block.get("id", "")).strip()
        if not cid:
            raise ExpError(f"{mod_id}: [[experiment]] #{i + 1} has no `id`")
        # The key format is exp.<id>.<field>; a dot or tab in an id would split
        # into a field the reader does not know. Refuse it here (unlike the Lua
        # side, which folds it -- a probe that raises on its own case name has
        # wasted the run it was measuring, but a manifest is read before that).
        if any(c in cid for c in ".\t\n"):
            raise ExpError(f"{mod_id}: experiment id {cid!r} may not contain . or whitespace")
        if cid in seen:
            raise ExpError(f"{mod_id}: duplicate experiment id {cid!r}")
        seen.add(cid)
        question = str(block.get("question", "")).strip()
        if not question:
            raise ExpError(f"{mod_id}: experiment {cid!r} has no `question`")
        out.append({"id": cid, "question": question[:MAX_TEXT]})
    return out


def declarations(game_dir: Path | str | None, mod_id: str) -> list[dict[str, str]]:
    """`[[experiment]]` blocks from an installed mod's manifest, or []."""
    path = mods_dir(game_dir) / mod_id / "manifest.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    try:
        return parse_declarations(raw.get("experiment"), mod_id=mod_id)
    except ExpError:
        # Reported by `rsmm lint`, which is where an author looks. Refusing to
        # print anyone's results because one manifest is malformed would be a
        # worse trade.
        return []


def read_cases(path: Path) -> list[dict[str, Any]]:
    """Every `exp.` case in one mod's state file, ordered by id."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    cases: dict[str, dict[str, Any]] = {}

    def slot(cid: str) -> dict[str, Any]:
        return cases.setdefault(
            cid, {"id": cid, "question": "", "status": NODATA, "why": "",
                  "at": None, "by": "", "observations": {}}
        )

    for key, value in parse_kv(text).items():
        if not key.startswith(PREFIX) or key == SESSION_KEY:
            continue
        cid, _, field = key[len(PREFIX):].partition(".")
        if not cid or not field:
            continue
        c = slot(cid)
        if field == "q":
            c["question"] = str(value)
        elif field == "why":
            c["why"] = str(value)
        elif field == "at":
            c["at"] = int(value) if isinstance(value, (int, float)) else None
        elif field == "by":
            c["by"] = str(value)
        elif field == "pass":
            c["status"] = PASS if value else FAIL
        elif field.startswith("o."):
            c["observations"][field[2:]] = value
    return [cases[k] for k in sorted(cases)]


def discover(game_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """`[{modId, session, cases}]` for every installed mod with results."""
    root = mods_dir(game_dir)
    out: list[dict[str, Any]] = []
    try:
        entries = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    for d in entries:
        path = state_file(game_dir, d.name)
        cases = read_cases(path)
        by_id = {c["id"]: c for c in cases}
        # A mod with no Lua can still declare what it wants to know. Merging
        # here rather than at render time is what makes the question visible
        # BEFORE the playtest, which is the only time it can still be changed.
        for decl in declarations(game_dir, d.name):
            c = by_id.get(decl["id"])
            if c is None:
                c = {"id": decl["id"], "question": "", "status": NODATA,
                     "why": "", "at": None, "by": "", "observations": {}}
                by_id[decl["id"]] = c
            # The manifest is the author's wording; a runtime declaration only
            # fills in when the manifest said nothing.
            c["question"] = decl["question"]
        if not by_id:
            continue
        session = None
        try:
            session = parse_kv(
                path.read_text(encoding="utf-8", errors="replace")
            ).get(SESSION_KEY)
        except OSError:
            pass
        out.append({
            "modId": d.name,
            "session": int(session) if isinstance(session, (int, float)) else None,
            "cases": [by_id[k] for k in sorted(by_id)],
        })
    return out


def _escape(s: str) -> str:
    """Inverse of `cmd_overlay._unescape` / the SDK's `_esc` (rsmm.lua)."""
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def serialize_kv(store: dict[str, Any]) -> str:
    """Render a kv store the way `R.kv.save` does, so the SDK can read it back.

    A hand-typed verdict has to survive the mod's NEXT launch reading this
    file, so it is written in the loader's own format rather than beside it.
    """
    lines = []
    for key in sorted(store):
        v = store[key]
        if isinstance(v, bool):
            lines.append(f"b\t{_escape(key)}\t{'1' if v else '0'}")
        elif isinstance(v, (int, float)):
            lines.append(f"n\t{_escape(key)}\t{v}")
        else:
            lines.append(f"s\t{_escape(key)}\t{_escape(str(v))}")
    return "\n".join(lines) + ("\n" if lines else "")


def answer(game_dir: Path | str | None, mod_id: str, case_id: str,
           passed: bool, why: str = "") -> Path:
    """Record a verdict a person observed, into the mod's own state file.

    Read-modify-write over the WHOLE store, never an append: the file also
    holds the mod's `R.kv` counters and its overlay rows, and rewriting only
    the experiment keys would drop them.
    """
    if any(c in case_id for c in ".\t\n"):
        raise ExpError(f"case id {case_id!r} may not contain . or whitespace")
    d = mods_dir(game_dir) / mod_id
    if not d.is_dir():
        raise ExpError(f"no installed mod {mod_id!r} — is it applied?")
    path = d / ".rsmm_state"
    store: dict[str, Any] = {}
    try:
        store = dict(parse_kv(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        pass
    store.setdefault(SESSION_KEY, int(time.time()))
    store[f"{PREFIX}{case_id}.pass"] = bool(passed)
    store[f"{PREFIX}{case_id}.why"] = why[:MAX_TEXT]
    store[f"{PREFIX}{case_id}.at"] = int(time.time())
    store[f"{PREFIX}{case_id}.by"] = BY_HUMAN
    # Temp-file + rename, the same contract the loader writes under: a verdict
    # is worth nothing if a half-written file eats the rest of the run's.
    tmp = path.with_suffix(f".rsmm_state.{os.getpid()}.tmp")
    tmp.write_text(serialize_kv(store), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _age(ts: int | None) -> str:
    if not ts:
        return ""
    secs = max(0, int(time.time()) - ts)
    if secs < 90:
        return f"{secs}s ago"
    if secs < 5400:
        return f"{secs // 60}m ago"
    if secs < 172800:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _fmt(v: Any) -> str:
    """Render an observation. Every `n` line comes back from `parse_kv` as a
    float, so a plain count would print as `245.0` — noise in the one place a
    reader is scanning for a number."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


_MARK = {
    PASS:   ("PASS", _ST.ok),
    FAIL:   ("FAIL", _ST.err),
    NODATA: ("----", _ST.dim),
}


def render(records: list[dict[str, Any]]) -> list[str]:
    if not records:
        return [
            "",
            "  " + _ST.dim("no experiment results in the installed mods."),
            "",
            "  A mod records them with R.exp — declare a hypothesis, close it",
            "  with a verdict, and they show up here after the next playtest:",
            "",
            "  " + _ST.dim('    R.exp.run("tile_placed", "is a mod tile placed?", fn)'),
            "",
        ]
    width = max(
        (len(c["id"]) for r in records for c in r["cases"]),
        default=10,
    )
    lines = [""]
    for rec in records:
        head = "  " + _ST.bold(rec["modId"])
        age = _age(rec["session"])
        if age:
            head += "  " + _ST.dim(age)
        lines.append(head)
        for c in rec["cases"]:
            label, paint = _MARK[c["status"]]
            why = c["why"] or (
                "declared, never resolved" if c["status"] == NODATA else ""
            )
            if c["by"] == BY_HUMAN:
                # A verdict somebody typed is a different grade of evidence
                # from one the game measured, and a table that hides the
                # difference is how an assumption becomes a fact.
                why = (why + "  " if why else "") + "(reported by you)"
            lines.append(f"    {paint(label)}  {c['id']:<{width}}  {why}")
            if c["question"]:
                lines.append(f"    {' ' * (len(label) + width + 4)}{_ST.dim(c['question'])}")
            for k, v in sorted(c["observations"].items()):
                lines.append("      " + _ST.dim(f"· {k} = {_fmt(v)}"))
        lines.append("")
    counts = {PASS: 0, FAIL: 0, NODATA: 0}
    for rec in records:
        for c in rec["cases"]:
            counts[c["status"]] += 1
    lines.append(
        "  " + _ST.dim(
            f"{counts[PASS]} pass, {counts[FAIL]} fail, {counts[NODATA]} no-data"
        )
    )
    lines.append("")
    return lines


def _answer_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm exp answer",
        description="record a verdict you observed on screen",
        epilog="Run this AFTER quitting the game: the loader rewrites the mod's "
               "state file when it exits, and would overwrite an answer typed "
               "while it is still running.",
    )
    ap.add_argument("mod_id", help="the mod whose experiment this is")
    ap.add_argument("case_id", help="the case id, as shown by `rsmm exp`")
    ap.add_argument("verdict", choices=("pass", "fail"),
                    help="did the thing happen?")
    ap.add_argument("-m", "--why", default="",
                    help="what you saw — this is the whole record in six months")
    ap.add_argument("--game-dir", default=None, help="game install directory")
    args = ap.parse_args(argv)
    try:
        answer(args.game_dir, args.mod_id, args.case_id,
               args.verdict == "pass", args.why)
    except ExpError as e:
        print(_ST.err(f"  {e}"))
        return 1
    print(f"  recorded {args.mod_id} / {args.case_id} = "
          f"{_ST.ok('PASS') if args.verdict == 'pass' else _ST.err('FAIL')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # A verb, not a flag: recording a verdict and reading the table are
    # different operations and sharing one flag set would let `rsmm exp --json
    # --pass` mean nothing in particular.
    if argv and argv[0] == "answer":
        return _answer_main(argv[1:])
    ap = argparse.ArgumentParser(
        prog="rsmm exp",
        description="show the hypotheses mods answered during a playtest "
                    "(recorded with R.exp, or with `rsmm exp answer`)",
        epilog="rsmm exp answer <mod> <case> pass|fail -m '...' records a "
               "verdict you saw on screen.",
    )
    ap.add_argument("mod_id", nargs="?", default=None,
                    help="mod to show; omit for every mod with results")
    ap.add_argument("--game-dir", default=None, help="game install directory")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    records = discover(args.game_dir)
    if args.mod_id:
        records = [r for r in records if r["modId"] == args.mod_id]

    if args.json:
        print(json.dumps(records, indent=2))
    else:
        print("\n".join(render(records)))

    # A FAIL is the only outcome that is an ANSWER of "no". NO-DATA means the
    # measurement never ran, which is worth seeing but is not a failed
    # hypothesis, so it does not fail the command.
    failed = any(c["status"] == FAIL for r in records for c in r["cases"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
