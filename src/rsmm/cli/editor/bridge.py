"""The editors without a socket, for the web editor on the docs site.

The docs site runs this package in the browser (Pyodide, in a worker), where
nothing can listen on a port. Its page routes each editor request here
instead, and ``request`` hands it to the same ``app.handle`` the local server
uses: same routes, same token, same refusals. There is no Host check, because
there is no network hop for a foreign page to reach.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from rsmm.cli.editor import app


class Bridge:
    def __init__(self, *, mods: Path | None = None, tab: str = "items"):
        self.ctx = app.Context(mods=mods, start=tab)

    @property
    def token(self) -> str:
        return self.ctx.token

    def request(self, method: str, target: str, body: bytes = b"",
                headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        r = app.handle(self.ctx, method, target, headers or {}, body)
        return r.status, {"Content-Type": r.ctype, **r.headers}, r.data

    def zip_mod(self, mod_id: str) -> bytes:
        """``mods/<mod_id>`` as a zip holding one ``<mod_id>/`` folder, ready
        to unpack into a real mods folder. The web editor's mods exist only in
        the page's memory, so this is how a saved mod leaves it."""
        from rsmm.cli.editor.content import _MOD_ID_RE
        if not _MOD_ID_RE.match(mod_id):
            raise ValueError(f"bad mod id {mod_id!r}")
        root = self.ctx.mods_dir
        if not (root / mod_id / "manifest.toml").is_file():
            raise ValueError(f"no mod {mod_id!r}")
        with tempfile.TemporaryDirectory() as tmp:
            made = shutil.make_archive(str(Path(tmp) / mod_id), "zip",
                                       root_dir=root, base_dir=mod_id)
            return Path(made).read_bytes()
