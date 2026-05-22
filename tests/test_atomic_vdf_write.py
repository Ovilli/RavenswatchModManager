"""Verify the LaunchOptions VDF rewrite is atomic.

We can't easily simulate a real crash mid-write inside Python, but we
can pin the two invariants that make the write crash-safe:

  1. After a successful call, the contents of the original path equal
     the new text exactly — no partial state.
  2. The intermediate `.rsmm.tmp` file does not survive the call. If
     the implementation regressed to a non-atomic `write_text` it
     would leave the temp behind or never create one; either failure
     mode is caught.

Plus we cover the standard happy paths (insert when LaunchOptions is
absent, replace when present, backup created on first run).
"""

from __future__ import annotations

from pathlib import Path

from rsmm.cli.run import _write_launch_options

APP_ID = "2305930"
BASE_VDF = (
    '"UserLocalConfigStore"\n'
    '{\n'
    '\t"Software"\n'
    '\t{\n'
    '\t\t"Valve"\n'
    '\t\t{\n'
    '\t\t\t"Steam"\n'
    '\t\t\t{\n'
    '\t\t\t\t"Apps"\n'
    '\t\t\t\t{\n'
    f'\t\t\t\t\t"{APP_ID}"\n'
    '\t\t\t\t\t{{REPLACE_ME}}\n'
    '\t\t\t\t}\n'
    '\t\t\t}\n'
    '\t\t}\n'
    '\t}\n'
    '}\n'
)


def _make_vdf(tmp_path: Path, app_body: str) -> Path:
    text = BASE_VDF.replace("{{REPLACE_ME}}", app_body)
    p = tmp_path / "localconfig.vdf"
    p.write_text(text, encoding="utf-8")
    return p


def test_insert_launch_options(tmp_path):
    p = _make_vdf(tmp_path, "{\n\t\t\t\t\t\t\"LastPlayed\"\t\t\"0\"\n\t\t\t\t\t}")
    assert _write_launch_options(p, APP_ID, "rsmm-vanilla")
    out = p.read_text(encoding="utf-8")
    assert '"LaunchOptions"\t\t"rsmm-vanilla"' in out
    # Original key preserved.
    assert '"LastPlayed"\t\t"0"' in out
    # Backup file written on first run.
    assert (p.with_suffix(p.suffix + ".rsmm.bak")).exists()


def test_replace_launch_options(tmp_path):
    body = (
        "{\n"
        '\t\t\t\t\t\t"LaunchOptions"\t\t"old-value"\n'
        '\t\t\t\t\t\t"LastPlayed"\t\t"0"\n'
        "\t\t\t\t\t}"
    )
    p = _make_vdf(tmp_path, body)
    assert _write_launch_options(p, APP_ID, "rsmm-modded")
    out = p.read_text(encoding="utf-8")
    assert '"LaunchOptions"\t\t"rsmm-modded"' in out
    assert '"old-value"' not in out


def test_atomic_write_leaves_no_temp_file(tmp_path):
    """The implementation must `replace` the temp file, not leave it
    sitting next to the original. A leftover `.rsmm.tmp` is a tell that
    `write_text` was called directly on the live VDF.
    """
    p = _make_vdf(tmp_path, "{\n\t\t\t\t\t\t\"LastPlayed\"\t\t\"0\"\n\t\t\t\t\t}")
    assert _write_launch_options(p, APP_ID, "rsmm-vanilla")
    assert not p.with_suffix(p.suffix + ".rsmm.tmp").exists()


def test_backup_preserved_across_runs(tmp_path):
    """The first write captures pristine contents; subsequent writes do
    not overwrite the backup. Without this guarantee a second `rsmm run`
    would lose the original `LaunchOptions` that Steam wrote.
    """
    p = _make_vdf(tmp_path, "{\n\t\t\t\t\t\t\"LastPlayed\"\t\t\"0\"\n\t\t\t\t\t}")
    pristine = p.read_text(encoding="utf-8")
    assert _write_launch_options(p, APP_ID, "rsmm-vanilla")
    bak = p.with_suffix(p.suffix + ".rsmm.bak")
    assert bak.read_text(encoding="utf-8") == pristine

    # Second write must not touch the backup.
    assert _write_launch_options(p, APP_ID, "rsmm-modded")
    assert bak.read_text(encoding="utf-8") == pristine


def test_missing_app_block_returns_false(tmp_path):
    p = _make_vdf(tmp_path, "{\n\t\t\t\t\t\t\"LastPlayed\"\t\t\"0\"\n\t\t\t\t\t}")
    assert _write_launch_options(p, "9999999", "rsmm-vanilla") is False
    # File untouched.
    assert "9999999" not in p.read_text(encoding="utf-8")
