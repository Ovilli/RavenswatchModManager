"""Loader update channel: signature verification, plant safety, replant logic.

The channel plants a DLL that is injected into the game process, so the
tests that matter most are the negative ones — a tampered manifest, a
tampered payload, a wrong key, a tarball trying to write outside the two
allowed destinations. Each of those must leave the installed loader
untouched.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tarfile
import time
import urllib.error
from pathlib import Path

import pytest

from rsmm.engine import loader_update as lu
from rsmm.engine import minisign
from rsmm.engine.minisign import MinisignError

# --- a test-only minisign signer ------------------------------------------
# The module under test can only verify (by design). Signing here reuses its
# curve constants so the round trip exercises the real verifier.

_L = minisign._L
_B = minisign._B


def _ed25519_keypair(seed: bytes) -> tuple[bytes, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return seed, _compress(minisign._scalar_mult(a, _B))


def _compress(p) -> bytes:
    zinv = pow(p[2], minisign._P - 2, minisign._P)
    x = p[0] * zinv % minisign._P
    y = p[1] * zinv % minisign._P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    prefix = h[32:]
    _, pk = _ed25519_keypair(seed)
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % _L
    rr = _compress(minisign._scalar_mult(r, _B))
    k = int.from_bytes(hashlib.sha512(rr + pk + msg).digest(), "little") % _L
    return rr + int.to_bytes((r + k * a) % _L, 32, "little")


KEY_ID = bytes.fromhex("0102030405060708")
SEED = bytes(range(32))


def _pubkey_text() -> str:
    _, pk = _ed25519_keypair(SEED)
    payload = base64.b64encode(b"Ed" + KEY_ID + pk).decode()
    return f"untrusted comment: test key\n{payload}\n"


def _sign(msg: bytes, *, key_id: bytes = KEY_ID, trusted: str = "test") -> str:
    sig = _ed25519_sign(SEED, msg)
    line2 = base64.b64encode(b"Ed" + key_id + sig).decode()
    gsig = base64.b64encode(_ed25519_sign(SEED, sig + trusted.encode())).decode()
    return (f"untrusted comment: sig\n{line2}\n"
            f"trusted comment: {trusted}\n{gsig}\n")


# --- minisign primitives --------------------------------------------------

def test_verify_round_trip():
    msg = b"payload bytes"
    assert minisign.verify(msg, _sign(msg), _pubkey_text()) == "test"


def test_verify_rejects_tampered_message():
    with pytest.raises(MinisignError, match="does not match the payload"):
        minisign.verify(b"other", _sign(b"payload bytes"), _pubkey_text())


def test_verify_rejects_foreign_key_id():
    msg = b"payload bytes"
    with pytest.raises(MinisignError, match="was made by key"):
        minisign.verify(msg, _sign(msg, key_id=b"\xff" * 8), _pubkey_text())


def test_verify_rejects_rewritten_trusted_comment():
    msg = b"payload bytes"
    sig = _sign(msg, trusted="v1")
    tampered = sig.replace("trusted comment: v1", "trusted comment: v999")
    with pytest.raises(MinisignError, match="trusted comment"):
        minisign.verify(msg, tampered, _pubkey_text())


def test_shipped_pubkey_matches_the_desktop_updater_key():
    """The channel reuses the key that signs the desktop bundles. If the two
    drift, every user's update silently starts failing verification."""
    conf = json.loads(
        (Path(__file__).resolve().parents[1]
         / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    tauri_pk = conf["plugins"]["updater"]["pubkey"]
    assert (minisign.PublicKey.parse(tauri_pk)
            == minisign.PublicKey.parse(lu.PUBLIC_KEY))


# --- destination allowlist ------------------------------------------------

@pytest.mark.parametrize("member", [
    "../evil.dll",
    "/etc/passwd",
    "lib/../../evil.lua",
    "lib\\evil.lua",
    "mods/evil/init.lua",
    "asset_map.json",
    "lib/",
    "",
    "C:/windows/system32/evil.dll",
    "lib/rsmm.lua:evil",        # NTFS alternate data stream
    "lib/evil.lua ",            # trailing space — Windows strips it
    "lib/evil.lua.",            # trailing dot — Windows strips it too
    "lib/ev\x00il.lua",          # embedded NUL
    "lib/ev\nil.lua",            # newline
    "lib/.",
    "lib/..",
])
def test_resolve_destination_rejects_everything_outside_the_allowlist(member):
    with pytest.raises(lu.LoaderUpdateError):
        lu.resolve_destination(member)


def test_resolve_destination_maps_the_two_allowed_prefixes():
    assert lu.resolve_destination("winhttp.dll") == ("winhttp.dll",)
    assert lu.resolve_destination("lib/rsmm.lua") == ("rsmm", "lib", "rsmm.lua")
    assert lu.resolve_destination("lib/rsmm/health.lua") == (
        "rsmm", "lib", "rsmm", "health.lua")


# --- channel end to end ---------------------------------------------------

PAYLOAD = {
    "winhttp.dll": b"MZ fake loader v2",
    "lib/rsmm.lua": b"-- sdk v2\n",
    "lib/rsmm/health.lua": b"-- health\n",
}


def _make_bundle(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _publish(tmp_path: Path, *, version: int = 2, abi: int = 1,
             files: dict[str, bytes] | None = None,
             bundle_files: dict[str, bytes] | None = None) -> Path:
    """Lay out a fake remote release under a file:// base."""
    files = PAYLOAD if files is None else files
    remote = tmp_path / "remote"
    remote.mkdir(exist_ok=True)
    bundle = _make_bundle(bundle_files if bundle_files is not None else files)
    (remote / lu.BUNDLE_NAME).write_bytes(bundle)
    manifest = {
        "abi": abi,
        "loader_version": version,
        "generated": "2026-08-18T00:00:00Z",
        "rsmm_version": "0.4.27",
        "bundle_name": lu.BUNDLE_NAME,
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "notes": "test bundle",
        "files": [
            {"path": p, "sha256": hashlib.sha256(d).hexdigest(), "size": len(d)}
            for p, d in sorted(files.items())
        ],
    }
    raw = json.dumps(manifest, indent=1).encode()
    (remote / lu.MANIFEST_NAME).write_bytes(raw)
    (remote / lu.SIGNATURE_NAME).write_text(_sign(raw), encoding="utf-8")
    return remote


@pytest.fixture
def channel(tmp_path, monkeypatch):
    monkeypatch.setenv("RSMM_LOADER_UPDATE_PUBKEY", _pubkey_text())
    monkeypatch.setattr(lu, "bundled_version", lambda: 1)
    game = tmp_path / "game"
    (game / "rsmm" / "lib").mkdir(parents=True)
    (game / "winhttp.dll").write_bytes(b"MZ fake loader v1")

    def use(remote: Path):
        monkeypatch.setenv("RSMM_LOADER_UPDATE_BASE", remote.as_uri())
    return game, use


def test_update_plants_dll_and_sdk(tmp_path, channel):
    game, use = channel
    use(_publish(tmp_path))

    state = lu.check(game)
    assert state["status"] == "update_available"
    assert (state["installed_version"], state["remote_version"]) == (1, 2)

    state = lu.apply_update(game, state)
    assert state["status"] == "updated"
    assert (game / "winhttp.dll").read_bytes() == PAYLOAD["winhttp.dll"]
    assert (game / "rsmm/lib/rsmm.lua").read_bytes() == PAYLOAD["lib/rsmm.lua"]
    assert (game / "rsmm/lib/rsmm/health.lua").exists()
    assert lu.planted_version(game) == 2
    assert lu.check(game)["status"] == "up_to_date"


def test_update_is_a_no_op_when_the_channel_is_behind(tmp_path, channel):
    game, use = channel
    use(_publish(tmp_path, version=1))
    assert lu.check(game)["status"] == "up_to_date"

    use(_publish(tmp_path, version=0))
    assert lu.check(game)["status"] == "ahead"


def test_malformed_manifest_is_an_error_not_a_needs_app_update(tmp_path, channel):
    """A missing 'abi' must not masquerade as "update the app" — that told
    users to reinstall when the real fault was a broken publish."""
    game, use = channel
    remote = _publish(tmp_path)
    manifest = json.loads((remote / lu.MANIFEST_NAME).read_text())
    del manifest["abi"]
    raw = json.dumps(manifest, indent=1).encode()
    (remote / lu.MANIFEST_NAME).write_bytes(raw)
    (remote / lu.SIGNATURE_NAME).write_text(_sign(raw), encoding="utf-8")
    use(remote)
    with pytest.raises(lu.LoaderUpdateError, match="no integer 'abi'") as exc:
        lu.check(game)
    assert not isinstance(exc.value, lu.AbiTooNewError)


def test_future_abi_reports_needs_app_update(tmp_path, channel):
    game, use = channel
    use(_publish(tmp_path, abi=lu.SUPPORTED_ABI + 1))
    state = lu.check(game)
    assert state["status"] == "needs_app_update"
    assert "update the app" in state["error"]
    with pytest.raises(lu.LoaderUpdateError):
        lu.apply_update(game)
    assert (game / "winhttp.dll").read_bytes() == b"MZ fake loader v1"


def test_tampered_manifest_leaves_the_installed_loader_alone(tmp_path, channel):
    game, use = channel
    remote = _publish(tmp_path)
    manifest = json.loads((remote / lu.MANIFEST_NAME).read_text())
    manifest["loader_version"] = 99
    (remote / lu.MANIFEST_NAME).write_bytes(json.dumps(manifest, indent=1).encode())
    use(remote)

    with pytest.raises(lu.LoaderUpdateError, match="signature rejected"):
        lu.check(game)
    assert (game / "winhttp.dll").read_bytes() == b"MZ fake loader v1"


def test_tampered_bundle_leaves_the_installed_loader_alone(tmp_path, channel):
    game, use = channel
    remote = _publish(tmp_path)
    (remote / lu.BUNDLE_NAME).write_bytes(_make_bundle(
        {**PAYLOAD, "winhttp.dll": b"MZ backdoored"}))
    use(remote)

    with pytest.raises(lu.LoaderUpdateError, match="bundle hash"):
        lu.apply_update(game)
    assert (game / "winhttp.dll").read_bytes() == b"MZ fake loader v1"


def test_bundle_member_outside_the_manifest_is_refused(tmp_path, channel):
    game, use = channel
    use(_publish(tmp_path, bundle_files={**PAYLOAD, "lib/extra.lua": b"-- extra"}))
    with pytest.raises(lu.LoaderUpdateError, match="not listed in the manifest"):
        lu.apply_update(game)
    assert not (game / "rsmm/lib/extra.lua").exists()


def test_manifest_claiming_a_path_outside_the_allowlist_is_refused(tmp_path, channel):
    game, use = channel
    use(_publish(tmp_path, files={"../../evil.dll": b"x"}))
    with pytest.raises(lu.LoaderUpdateError):
        lu.check(game)


def test_signature_from_the_wrong_key_is_refused(tmp_path, channel, monkeypatch):
    game, use = channel
    use(_publish(tmp_path))
    monkeypatch.setenv("RSMM_LOADER_UPDATE_PUBKEY", lu.PUBLIC_KEY)  # real key
    with pytest.raises(lu.LoaderUpdateError, match="signature rejected"):
        lu.check(game)


def test_replant_cached_survives_a_restore(tmp_path, channel):
    """`restore --all` wipes the loader; `install-loader` replants the copy
    bundled in this build. Without the cache that silently downgrades a user
    who is ahead via the channel."""
    game, use = channel
    use(_publish(tmp_path))
    lu.apply_update(game)

    # Simulate restore --all + install-loader planting the bundled (v1) files.
    (game / "winhttp.dll").write_bytes(b"MZ fake loader v1")
    (game / "rsmm/lib/rsmm.lua").write_bytes(b"-- sdk v1\n")
    lu.planted_manifest_path(game).unlink()

    result = lu.replant_cached(game)
    assert result and result["loader_version"] == 2
    assert (game / "winhttp.dll").read_bytes() == PAYLOAD["winhttp.dll"]
    assert lu.planted_version(game) == 2


def test_replant_cached_is_a_no_op_without_a_cache(tmp_path, channel):
    game, _ = channel
    assert lu.replant_cached(game) is None


def test_replant_cached_refuses_a_corrupted_cache(tmp_path, channel):
    game, use = channel
    use(_publish(tmp_path))
    lu.apply_update(game)
    (lu.cache_dir(game) / "payload" / "winhttp.dll").write_bytes(b"MZ tampered")
    with pytest.raises(lu.LoaderUpdateError, match="corrupt"):
        lu.replant_cached(game)


def test_replant_cached_refuses_a_resigned_cache(tmp_path, channel):
    """The cache lives in the game directory, which is not a trusted store."""
    game, use = channel
    use(_publish(tmp_path))
    lu.apply_update(game)
    cache = lu.cache_dir(game)
    (cache / lu.MANIFEST_NAME).write_bytes(b'{"abi":1,"loader_version":99}')
    with pytest.raises(lu.LoaderUpdateError, match="rejected"):
        lu.replant_cached(game)


def test_bundled_version_is_stamped_and_matches_the_supported_abi():
    """A missing or unbumped stamp silently disables the downgrade guard."""
    data = json.loads(
        (Path(__file__).resolve().parents[1]
         / "data" / lu.VERSION_FILE).read_text(encoding="utf-8")
    )
    assert data["loader_version"] >= 1
    assert data["abi"] == lu.SUPPORTED_ABI


def test_manifest_with_a_duplicate_path_is_refused(tmp_path, channel):
    """Two hashes for one destination — which wins would depend on dict
    ordering, so refuse rather than pick."""
    game, use = channel
    remote = _publish(tmp_path)
    manifest = json.loads((remote / lu.MANIFEST_NAME).read_text())
    manifest["files"].append(dict(manifest["files"][0]))
    raw = json.dumps(manifest, indent=1).encode()
    (remote / lu.MANIFEST_NAME).write_bytes(raw)
    (remote / lu.SIGNATURE_NAME).write_text(_sign(raw), encoding="utf-8")
    use(remote)
    with pytest.raises(lu.LoaderUpdateError, match="twice"):
        lu.check(game)


def test_a_locked_dll_plants_nothing_at_all(tmp_path, channel):
    """Ravenswatch running holds winhttp.dll open. Planting the SDK anyway
    and only then failing leaves a new SDK calling into an old DLL.

    A read-only destination stands in for the Windows lock: note that
    `os.replace` would happily replace it (the *directory* is writable),
    so this also proves the pre-flight catches what the plant itself
    would not.
    """
    # POSIX root ignores the permission bits this relies on; Windows has no
    # euid at all (`os.geteuid` simply does not exist there), and its
    # read-only attribute does block opening for write, so the test is real
    # on Windows and only the root case needs skipping.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores the permission bits this test relies on")
    game, use = channel
    use(_publish(tmp_path))
    sdk = game / "rsmm/lib/rsmm.lua"
    sdk.write_bytes(b"-- sdk v1\n")
    dll = game / "winhttp.dll"
    dll.chmod(0o444)
    try:
        with pytest.raises(lu.LoaderUpdateError, match="close Ravenswatch"):
            lu.apply_update(game)
        # Nothing moved: not the DLL, and crucially not the SDK either.
        assert dll.read_bytes() == b"MZ fake loader v1"
        assert sdk.read_bytes() == b"-- sdk v1\n"
        assert not lu.planted_manifest_path(game).exists()
    finally:
        dll.chmod(0o644)


def test_replant_refuses_a_cache_file_of_the_wrong_size(tmp_path, channel):
    game, use = channel
    use(_publish(tmp_path))
    lu.apply_update(game)
    (lu.cache_dir(game) / "payload" / "winhttp.dll").write_bytes(b"x" * 999)
    with pytest.raises(lu.LoaderUpdateError, match="corrupt"):
        lu.replant_cached(game)


def test_pubkey_override_is_ignored_in_a_frozen_build(monkeypatch):
    """Every end user runs the frozen sidecar. An env var that swaps the
    trust root there is an env var that installs an arbitrary DLL."""
    monkeypatch.setenv("RSMM_LOADER_UPDATE_PUBKEY", "untrusted comment: evil\nAAAA\n")
    assert lu.public_key() != lu.PUBLIC_KEY          # source checkout: honoured
    monkeypatch.setattr(lu.sys, "frozen", True, raising=False)
    assert lu.public_key() == lu.PUBLIC_KEY          # frozen: embedded key only


def test_frozen_builds_refuse_non_https_urls(monkeypatch):
    """A source checkout serves test channels off disk; a user build has no
    reason to read a local URL, so it cannot."""
    assert lu._fetch.__module__  # sanity: symbol exists
    monkeypatch.setattr(lu.sys, "frozen", True, raising=False)
    with pytest.raises(lu.LoaderUpdateError, match="non-HTTPS"):
        lu._fetch("file:///etc/passwd")
    assert lu._allowed_schemes() == ("https://",)


def test_a_second_update_refuses_while_one_is_in_flight(tmp_path, channel):
    """Two plants interleaving can mix files from different versions."""
    game, use = channel
    use(_publish(tmp_path))
    with lu._update_lock(game):
        with pytest.raises(lu.LoaderUpdateError, match="already running"):
            lu.apply_update(game)
    # Lock released on exit — the next attempt goes through.
    assert lu.apply_update(game)["status"] == "updated"


def test_a_stale_lock_is_reclaimed(tmp_path, channel):
    """A process that died mid-update must not wedge updates forever."""
    game, use = channel
    use(_publish(tmp_path))
    lock = game / "rsmm" / lu._LOCK_NAME
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999")
    old = time.time() - lu._LOCK_STALE_SECONDS - 60
    os.utime(lock, (old, old))
    assert lu.apply_update(game)["status"] == "updated"
    assert not lock.exists()


def test_staging_files_are_pid_qualified(tmp_path, channel):
    """Two planters sharing a staging name make the first consume the
    second's file, and the second fails with a bewildering ENOENT."""
    game, use = channel
    use(_publish(tmp_path))
    lu.apply_update(game)
    assert not list(game.rglob("*.rsmm-new"))
    assert not list(game.rglob("*.tmp"))


def test_an_unpublished_channel_is_a_status_not_an_error(tmp_path, channel, monkeypatch):
    """Every build shipped before the first publish would otherwise report a
    hard error on each launch for a channel that is simply not live yet."""
    game, _ = channel

    def _404(req, *a, **kw):
        url = getattr(req, "full_url", str(req))
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(lu.urllib.request, "urlopen", _404)
    state = lu.check(game)
    assert state["status"] == "not_published"
    assert state["installed_version"] == 1


# --- "installed" vs "what the game actually loads" -------------------------

def test_check_reports_a_plant_older_than_the_bundled_copy(tmp_path, channel, monkeypatch):
    """`installed_version` is update ELIGIBILITY, not what is installed.

    It folds in the bundled stamp so the channel cannot re-plant a payload
    this build already carries. The cost is that an older PLANTED copy — the
    one the game actually loads — hides behind a newer bundled number, and
    `update-loader` answers "up to date" for a game dir that is behind. That
    is what sent a 2026-08-24 session hunting the bug in the mod for three
    game restarts. The flag exists so a human is told.
    """
    game, use = channel
    use(_publish(tmp_path, version=3))
    lu.planted_manifest_path(game).parent.mkdir(parents=True, exist_ok=True)
    lu.planted_manifest_path(game).write_text(json.dumps({"loader_version": 2}),
                                              encoding="utf-8")
    monkeypatch.setattr(lu, "bundled_version", lambda: 5)

    state = lu.check(game)
    assert state["planted_version"] == 2      # what the game loads
    assert state["bundled_version"] == 5
    assert state["installed_version"] == 5    # eligibility, unchanged
    assert state["plant_stale"] is True
    assert state["status"] == "ahead"         # channel v3 < bundled v5


def test_check_does_not_cry_stale_for_a_current_plant(tmp_path, channel, monkeypatch):
    game, use = channel
    use(_publish(tmp_path, version=1))
    lu.planted_manifest_path(game).parent.mkdir(parents=True, exist_ok=True)
    lu.planted_manifest_path(game).write_text(json.dumps({"loader_version": 4}),
                                              encoding="utf-8")
    monkeypatch.setattr(lu, "bundled_version", lambda: 4)
    assert lu.check(game)["plant_stale"] is False


def test_check_does_not_cry_stale_when_nothing_is_planted(tmp_path, channel):
    """No manifest means install-loader has never run. `check_loader` in doctor
    already says that; claiming the plant is *stale* would be a second, wronger
    way to say it."""
    game, use = channel
    use(_publish(tmp_path))
    state = lu.check(game)
    assert state["planted_version"] is None
    assert state["plant_stale"] is False
