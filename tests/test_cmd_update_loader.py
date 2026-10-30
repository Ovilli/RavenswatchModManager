"""`rsmm update-loader` refreshes the pattern DB alongside a new SDK."""

import json

from rsmm.cli import cmd_update_loader as cmd
from rsmm.engine import data_update


def _stub(monkeypatch, db_status):
    calls = []
    monkeypatch.setattr(cmd, "check", lambda g: {"status": "update_available"})
    updated = {"status": "updated", "installed_version": 50}
    monkeypatch.setattr(cmd, "apply_update", lambda g, s: updated)
    monkeypatch.setattr(data_update, "check", lambda g: {"status": db_status})
    monkeypatch.setattr(data_update, "apply_update", lambda g, s: calls.append(g))
    return calls


def test_update_refreshes_a_stale_pattern_db_and_keeps_json_clean(tmp_path, monkeypatch, capsys):
    calls = _stub(monkeypatch, "update_available")
    assert cmd.main(["--json", "--game-dir", str(tmp_path)]) == 0
    assert calls == [tmp_path]
    assert json.loads(capsys.readouterr().out)["status"] == "updated"


def test_update_leaves_a_current_pattern_db_alone(tmp_path, monkeypatch):
    calls = _stub(monkeypatch, "up_to_date")
    assert cmd.main(["--game-dir", str(tmp_path)]) == 0
    assert calls == []


def test_pattern_db_fetch_failure_does_not_fail_the_update(tmp_path, monkeypatch):
    _stub(monkeypatch, "up_to_date")

    def boom(g):
        raise data_update.DataUpdateError("offline")
    monkeypatch.setattr(data_update, "check", boom)
    assert cmd.main(["--game-dir", str(tmp_path)]) == 0
