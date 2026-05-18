"""The /api/install endpoint accepts user-supplied zip bytes and
extracts them under mods/<id>/. Two attacks must be refused before
any extraction happens:

  1. Absolute-path zip entries (`/etc/passwd`).
  2. `..` traversal entries (`Evil/../etc/passwd`).
"""

import io
import zipfile


MANIFEST = (
    '[mod]\n'
    'id          = "EvilTestMod"\n'
    'name        = "Evil"\n'
    'version     = "1.0.0"\n'
    'author      = "test"\n'
    'enabled     = false\n'
)


def _zip_with(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return buf.getvalue()


def test_install_zip_rejects_absolute_path():
    from rsmm.cli.gui import _install_zip

    raw = _zip_with({
        "EvilTestMod/manifest.toml": MANIFEST.encode("utf-8"),
        "/etc/passwd": b"root:x:0:0:pwned\n",
    })
    r = _install_zip(raw)
    assert r["ok"] is False, f"expected rejection, got {r!r}"
    assert "unsafe" in r["msg"].lower() or "refus" in r["msg"].lower()


def test_install_zip_rejects_dotdot_traversal():
    from rsmm.cli.gui import _install_zip

    raw = _zip_with({
        "EvilTestMod/manifest.toml": MANIFEST.encode("utf-8"),
        "EvilTestMod/../etc/passwd": b"root:x:0:0:pwned\n",
    })
    r = _install_zip(raw)
    assert r["ok"] is False, f"expected rejection, got {r!r}"
    assert "unsafe" in r["msg"].lower() or "refus" in r["msg"].lower()
