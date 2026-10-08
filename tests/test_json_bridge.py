"""Characterization tests for the desktop/web JSON bridge.

These pin the JSON contract the desktop app depends on (so the planned
split into cli/json_* modules cannot change behaviour) and lock the two
security guards: the upload SSRF allowlist and the download zip extractor
(zip-slip + dangerous-extension blocking).
"""

import json
import zipfile
from pathlib import Path

import pytest

from rsmm.cli import json_bridge


def _emit_json(capsys):
    """Parse the single JSON blob cmd_* writes to stdout via _emit."""
    return json.loads(capsys.readouterr().out)


# --- _slugify --------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("My Cool Mod", "my-cool-mod"),
    ("  Trailing--Dashes  ", "trailing-dashes"),
    ("UPPER_under", "upper_under"),
    ("--leading", "leading"),
    ("!!!", ""),
    ("a.b.c", "a-b-c"),
])
def test_slugify(raw, want):
    assert json_bridge._slugify(raw) == want


# --- _upload_url_allowed (SSRF allowlist) ----------------------------------

@pytest.mark.parametrize("url", [
    "https://s3-rsmm.me/bucket/key",
    "https://ravenswatch-mods.s3.amazonaws.com/x",
])
def test_upload_url_allowed_known_hosts(url):
    assert json_bridge._upload_url_allowed(url) is True


@pytest.mark.parametrize("url", [
    "https://evil.example.com/x",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata SSRF
    "https://s3-rsmm.me.evil.com/x",  # suffix trick
    "not a url",
    "",
])
def test_upload_url_allowed_rejects(url):
    assert json_bridge._upload_url_allowed(url) is False


def test_upload_url_allowlist_extra_is_module_load_only(monkeypatch):
    # Mutating the env after import must NOT widen the allowlist (the guard
    # snapshots RSMM_UPLOAD_HOST_ALLOW at load to defeat mid-process injection).
    monkeypatch.setenv("RSMM_UPLOAD_HOST_ALLOW", "attacker.test")
    assert json_bridge._upload_url_allowed("https://attacker.test/x") is False


# --- _extract_downloaded_zip (zip-slip + dangerous ext) --------------------

def _make_zip(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    z = tmp_path / "mod.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return z


def test_extract_blocks_dangerous_extension(tmp_path):
    z = _make_zip(tmp_path, {"manifest.toml": b"", "payload.exe": b"MZ"})
    res = json_bridge._extract_downloaded_zip(z, tmp_path / "out", "evilmod")
    assert res and res["ok"] is False and "blocked file type" in res["error"]


def test_extract_refuses_zip_slip(tmp_path):
    z = _make_zip(tmp_path, {"manifest.toml": b"", "../escape.txt": b"x"})
    res = json_bridge._extract_downloaded_zip(z, tmp_path / "out", "slip")
    assert res and res["ok"] is False
    assert "traversal" in res["error"] or "escapes target" in res["error"]


def test_extract_requires_manifest(tmp_path):
    z = _make_zip(tmp_path, {"readme.txt": b"hi"})
    res = json_bridge._extract_downloaded_zip(z, tmp_path / "out", "nomani")
    assert res and res["ok"] is False and "manifest.toml" in res["error"]


def test_extract_happy_path_strips_single_top_dir(tmp_path):
    # A single wrapping top dir is stripped; files land directly under target.
    z = _make_zip(tmp_path, {
        "MyMod/manifest.toml": b"[mod]\nname='x'\n",
        "MyMod/assets/a.bin": b"DATA",
    })
    out = tmp_path / "out"
    res = json_bridge._extract_downloaded_zip(z, out, "mymod")
    assert res is None  # success
    assert (out / "manifest.toml").is_file()
    assert (out / "assets" / "a.bin").read_bytes() == b"DATA"


# --- cmd_list / _read_manifest (JSON contract) -----------------------------

def _write_mod(mods: Path, mod_id: str, body: str, assets: dict[str, bytes] | None = None):
    d = mods / mod_id
    d.mkdir(parents=True)
    (d / "manifest.toml").write_text(body, encoding="utf-8")
    for rel, data in (assets or {}).items():
        f = d / "assets" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)


def test_cmd_list_shape(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    _write_mod(
        mods, "CoolMod",
        '[mod]\nname = "Cool"\nversion = "1.2.3"\nauthor = "me"\nenabled = true\n',
        assets={"foo/bar.bin": b"x"},
    )
    _write_mod(mods, "_skipme", '[mod]\nname = "hidden"\n')  # underscore -> skipped
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)

    assert json_bridge.cmd_list() == 0
    items = _emit_json(capsys)
    assert [i["id"] for i in items] == ["CoolMod"]
    it = items[0]
    assert it["slug"] == "CoolMod" and it["version"] == "1.2.3"
    assert it["enabled"] is True
    assert it["writes"] == ["foo/bar.bin"]
    assert it["hasConfig"] is False


def test_cmd_list_reports_which_mods_are_configurable(tmp_path, monkeypatch, capsys):
    """The desktop library offers a Configure control per row from this flag.

    It has to arrive with the list: asking `config get` once per installed mod
    just to learn a boolean is one CLI spawn per mod.
    """
    mods = tmp_path / "mods"
    _write_mod(mods, "Plain", '[mod]\nname = "Plain"\n')
    _write_mod(mods, "Tunable", '[mod]\nname = "Tunable"\n')
    (mods / "Tunable" / "config_schema.toml").write_text(
        '[fields.speed]\ntype = "float"\ndefault = 1.0\n', encoding="utf-8"
    )
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)

    assert json_bridge.cmd_list() == 0
    flags = {i["id"]: i["hasConfig"] for i in _emit_json(capsys)}
    assert flags == {"Plain": False, "Tunable": True}


def test_cmd_list_empty_when_no_mods_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(json_bridge, "MODS_DIR", tmp_path / "nope")
    assert json_bridge.cmd_list() == 0
    assert _emit_json(capsys) == []


def test_cmd_list_fails_loudly_when_the_folder_cannot_be_read(tmp_path, monkeypatch):
    """An unreadable mods folder must NOT look like "no mods installed".

    Regression: both cases emitted `[]`, so the desktop app recorded "nothing
    is installed" from a transient permission error, then refused to install
    mods it believed were already there.
    """
    mods = tmp_path / "mods"
    mods.mkdir()
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)

    def boom(*_a, **_k):
        raise PermissionError("nope")

    monkeypatch.setattr(json_bridge.Path, "iterdir", boom)
    assert json_bridge.cmd_list() == 1


# --- cmd_uninstall_mod (path-traversal guard) ------------------------------

def test_uninstall_rejects_traversal(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    mods.mkdir()
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)
    json_bridge.cmd_uninstall_mod("../secrets")
    res = _emit_json(capsys)
    assert res["ok"] is False and "invalid mod id" in res["error"]


def test_uninstall_removes_existing(tmp_path, monkeypatch, capsys):
    mods = tmp_path / "mods"
    _write_mod(mods, "Doomed", '[mod]\nname = "d"\n')
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)
    json_bridge.cmd_uninstall_mod("Doomed")
    res = _emit_json(capsys)
    assert res["ok"] is True and res["removed"] is True
    assert not (mods / "Doomed").exists()


@pytest.mark.parametrize("mod_id", [".", "", "Keep/..", "Keep\\..", "C:Keep"])
def test_uninstall_never_takes_the_mods_folder_itself(tmp_path, monkeypatch, capsys, mod_id):
    """`.` resolves to mods/ itself; removing it would delete every mod."""
    mods = tmp_path / "mods"
    _write_mod(mods, "Keep", '[mod]\nname = "k"\n')
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)
    json_bridge.cmd_uninstall_mod(mod_id)
    res = _emit_json(capsys)
    assert res["ok"] is False and "invalid mod id" in res["error"]
    assert (mods / "Keep" / "manifest.toml").is_file()


_MARKER_HOOK = (
    "import os\nfrom pathlib import Path\n"
    "Path(os.environ['RSMM_GAME_DIR'], 'hook-ran.txt').write_text('x')\n"
)


@pytest.fixture()
def hooked_mod(tmp_path, monkeypatch):
    """An enabled mod that ships an on_disable.py, and the install it was applied to."""
    from rsmm.cli import apply_mods
    mods = tmp_path / "mods"
    _write_mod(mods, "Seedy", '[mod]\nname = "s"\n')
    (mods / "Seedy" / "on_disable.py").write_text(_MARKER_HOOK, encoding="utf-8")
    game = tmp_path / "game"
    cooking = game / "DarkTalesResources" / "_Cooking"
    cooking.mkdir(parents=True)
    state = apply_mods.State(cooking)
    state.set_enabled_mods(["Seedy"])
    state.save()
    monkeypatch.setattr(json_bridge, "MODS_DIR", mods)
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: game)
    return mods, game


def test_uninstall_asks_before_running_a_mods_hook(hooked_mod, capsys):
    """The hook is the mod author's Python, run as the user: never unasked."""
    mods, game = hooked_mod
    json_bridge.cmd_uninstall_mod("Seedy")
    res = _emit_json(capsys)
    assert res["ok"] is False
    assert res["needsHookConsent"] is True
    assert res["hookPath"].endswith("on_disable.py")
    assert not (game / "hook-ran.txt").exists()
    assert (mods / "Seedy").is_dir(), "nothing is removed until the user answers"


def test_uninstall_runs_the_hook_when_told_to(hooked_mod, capsys):
    mods, game = hooked_mod
    json_bridge.cmd_uninstall_mod("Seedy", "run")
    res = _emit_json(capsys)
    assert res["ok"] is True and res["disableHook"] == "ok", res
    assert (game / "hook-ran.txt").is_file()
    assert not (mods / "Seedy").exists()


def test_uninstall_skips_the_hook_when_declined(hooked_mod, capsys):
    mods, game = hooked_mod
    json_bridge.cmd_uninstall_mod("Seedy", "skip")
    res = _emit_json(capsys)
    assert res["ok"] is True and res["disableHook"] == "skipped"
    assert not (game / "hook-ran.txt").exists()
    assert not (mods / "Seedy").exists()


def test_uninstall_flags_reach_the_command(hooked_mod, capsys):
    _, game = hooked_mod
    assert json_bridge.main(["uninstall-mod", "Seedy", "--skip-hook"]) == 0
    assert _emit_json(capsys)["disableHook"] == "skipped"
    assert not (game / "hook-ran.txt").exists()


# --- cmd_loader_log (desktop Log tab) --------------------------------------

def _write_log(tmp_path: Path, text: str) -> Path:
    game = tmp_path / "Ravenswatch"
    (game / "mods").mkdir(parents=True)
    (game / "mods" / "_log.txt").write_text(text)
    return game


def test_loader_log_missing_is_not_an_error(tmp_path, monkeypatch, capsys):
    """A fresh install has no log until the game runs once with the loader.

    Reporting that as a failure would put a red error in the Log tab for
    every new user; `exists: false` lets the UI explain instead.
    """
    game = tmp_path / "Ravenswatch"
    game.mkdir()
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: game)
    assert json_bridge.cmd_loader_log() == 0
    out = _emit_json(capsys)
    assert out["exists"] is False
    assert out["lines"] == []
    assert out["path"].endswith("_log.txt")


def test_loader_log_returns_only_the_latest_session_by_default(tmp_path, monkeypatch, capsys):
    game = _write_log(
        tmp_path,
        "== SESSION one ==\nold line\n== SESSION two ==\nnew line\nnewer line\n",
    )
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: game)
    assert json_bridge.cmd_loader_log() == 0
    out = _emit_json(capsys)
    assert out["lines"] == ["== SESSION two ==", "new line", "newer line"]
    assert out["sessions"] == 2
    assert out["truncated"] is False


def test_loader_log_all_sessions_and_line_cap(tmp_path, monkeypatch, capsys):
    game = _write_log(
        tmp_path,
        "== SESSION one ==\nold line\n== SESSION two ==\nnew line\n",
    )
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: game)

    assert json_bridge.cmd_loader_log(all_sessions=True) == 0
    assert _emit_json(capsys)["lines"][0] == "== SESSION one =="

    assert json_bridge.cmd_loader_log(all_sessions=True, lines=2) == 0
    out = _emit_json(capsys)
    # Keeps the TAIL — the newest lines are the interesting ones.
    assert out["lines"] == ["== SESSION two ==", "new line"]
    assert out["truncated"] is True


def test_loader_log_without_session_banners_returns_everything(tmp_path, monkeypatch, capsys):
    """Logs from a loader predating session banners must not come back empty."""
    game = _write_log(tmp_path, "just a line\nand another\n")
    monkeypatch.setattr(json_bridge, "find_game_dir", lambda: game)
    assert json_bridge.cmd_loader_log() == 0
    assert _emit_json(capsys)["lines"] == ["just a line", "and another"]


def test_list_profiles_reads_sibling_profiles_in_one_call(tmp_path, monkeypatch, capsys):
    """The Profiles screen needs every profile's mods; one process, not one each."""
    root = tmp_path / "profiles"
    _write_mod(root / "solo", "alpha", '[mod]\nname = "Alpha"\n')
    _write_mod(root / "coop", "beta", '[mod]\nname = "Beta"\n')
    _write_mod(root / "coop", "gamma", '[mod]\nname = "Gamma"\n')
    monkeypatch.setattr(json_bridge, "MODS_DIR", root / "solo")  # the active profile

    assert json_bridge.cmd_list_profiles(["coop", "solo"]) == 0
    got = _emit_json(capsys)["profiles"]
    assert [m["id"] for m in got["coop"]["mods"]] == ["beta", "gamma"]
    assert [m["id"] for m in got["solo"]["mods"]] == ["alpha"]
    assert got["coop"]["ok"] and got["solo"]["ok"]


def test_list_profiles_a_missing_folder_is_empty_not_an_error(tmp_path, monkeypatch, capsys):
    root = tmp_path / "profiles"
    (root / "solo").mkdir(parents=True)
    monkeypatch.setattr(json_bridge, "MODS_DIR", root / "solo")
    assert json_bridge.cmd_list_profiles(["never-made"]) == 0
    assert _emit_json(capsys)["profiles"]["never-made"] == {"ok": True, "mods": []}


def test_list_profiles_refuses_an_id_that_is_not_a_plain_name(tmp_path, monkeypatch, capsys):
    """An id becomes a folder name; nothing with a separator or a dot may reach a path."""
    root = tmp_path / "profiles"
    _write_mod(tmp_path, "outside", '[mod]\nname = "Not a profile mod"\n')
    (root / "solo").mkdir(parents=True)
    monkeypatch.setattr(json_bridge, "MODS_DIR", root / "solo")
    bad = ["..", "../outside", "a/b", ".hidden", "", "x" * 65]
    assert json_bridge.cmd_list_profiles(bad) == 0
    got = _emit_json(capsys)["profiles"]
    assert all(v["ok"] is False for v in got.values())
    assert len(got) == len(set(bad))
