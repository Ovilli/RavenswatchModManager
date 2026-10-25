"""`rsmm json serve`: read-only commands from one warm process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rsmm.cli.json_serve import handle

REPO = Path(__file__).resolve().parents[1]


def test_refuses_writes():
    for args in (["apply"], ["install-mod", "x"], ["doctor", "--fix"], []):
        code, out, _ = handle(args)
        assert code == 2 and out == ""


def test_protocol_round_trip(tmp_path):
    env = {**os.environ, "RSMM_MODS_DIR": str(tmp_path / "mods"),
           "RSMM_GAME_DIR": str(tmp_path / "game")}
    (tmp_path / "mods").mkdir()
    reqs = "".join(json.dumps({"id": i, "args": a}) + "\n"
                   for i, a in ((1, ["list"]), (2, ["apply"]), (3, ["list"])))
    proc = subprocess.run([sys.executable, str(REPO / "rsmm"), "json", "serve"], input=reqs,
                          capture_output=True, text=True, env=env, timeout=120)
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["code"] == 0 and json.loads(replies[0]["stdout"]) == []
    assert replies[1]["code"] == 2
    assert replies[2]["stdout"] == replies[0]["stdout"]
