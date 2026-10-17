"""The `cli` channel: signed manifest -> per-platform archive -> <dest>/staged."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from test_loader_update import _pubkey_text, _sign

from rsmm.engine import cli_update as cu


def _archive(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _publish(remote: Path, *, version=2, abi=1, members=None, tamper=False) -> None:
    remote.mkdir(exist_ok=True)
    members = members or {cu.exe_name(): b"#!fake", "_internal/data/x.json": b"{}"}
    blob = _archive(members)
    name = f"rsmm-cli-{cu.platform_key()}.tar.gz"
    (remote / name).write_bytes(blob + (b"x" if tamper else b""))
    raw = json.dumps({
        "abi": abi, "cli_version": version, "notes": "n",
        "platforms": {cu.platform_key(): {"name": name,
                                          "sha256": hashlib.sha256(blob).hexdigest()}},
    }).encode()
    (remote / cu.MANIFEST_NAME).write_bytes(raw)
    (remote / cu.SIGNATURE_NAME).write_text(_sign(raw), encoding="utf-8")


@pytest.fixture
def remote(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_LOADER_UPDATE_PUBKEY", _pubkey_text())
    monkeypatch.setattr(cu, "own_stamp", lambda: (1, 1))
    r = tmp_path / "remote"
    monkeypatch.setenv("RSMM_CLI_UPDATE_BASE", r.as_uri())
    return r


def test_stages_a_newer_build(tmp_path, remote):
    _publish(remote)
    dest = tmp_path / "cli"
    assert cu.run(dest)["status"] == "staged"
    assert (dest / "staged" / cu.exe_name()).read_bytes() == b"#!fake"
    assert json.loads((dest / "staged" / cu.STAMP_NAME).read_text())["cli_version"] == 2
    # A second run sees the staged copy and does nothing.
    assert cu.run(dest)["status"] == "up_to_date"


def test_not_newer_than_the_running_cli_is_a_no_op(tmp_path, remote):
    _publish(remote, version=1)
    assert cu.run(tmp_path / "cli")["status"] == "up_to_date"
    assert not (tmp_path / "cli" / "staged").exists()


def test_other_abi_never_stages(tmp_path, remote):
    _publish(remote, abi=2)
    assert cu.run(tmp_path / "cli")["status"] == "needs_app_update"
    assert not (tmp_path / "cli" / "staged").exists()


def test_tampered_archive_is_refused(tmp_path, remote):
    _publish(remote, tamper=True)
    with pytest.raises(cu.CliUpdateError, match="does not match"):
        cu.run(tmp_path / "cli")
    assert not (tmp_path / "cli" / "staged").exists()


@pytest.mark.parametrize("bad", ["../evil", "/abs", "a\\b", "C:x"])
def test_member_escaping_the_payload_is_refused(tmp_path, remote, bad):
    _publish(remote, members={cu.exe_name(): b"x", bad: b"x"})
    with pytest.raises(cu.CliUpdateError, match="escapes"):
        cu.run(tmp_path / "cli")
    assert not (tmp_path / "cli" / "staged").exists()
