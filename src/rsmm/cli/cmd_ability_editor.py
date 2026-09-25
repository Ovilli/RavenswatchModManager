"""`rsmm ability-editor` — see a hero's abilities as graphs and build edits.

    rsmm ability-editor              open the page (hero picker)
    rsmm ability-editor --port 9000

A local page (127.0.0.1 only) that draws each ability of a shipped hero as a
graph of parts and the links between them, shows every part's fields by name,
and builds ``[[content.abilities]]`` steps as you set values, re-point links
and copy groups. Every change re-runs the steps and the pre-apply checks on
the server, so the page shows the edited graph and anything the build would
refuse. The page never writes a mod: copy the TOML into a custom hero's
manifest (``kind = "hero"``) and run ``rsmm apply``.
"""

from __future__ import annotations

import argparse
import json
import secrets
import struct
import sys
import threading
import webbrowser
from functools import cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


@cache
def _heroes() -> list[str]:
    """Shipped heroes with a gameplay entity (``Hero_<Name>/Hero_<Name>.entity``)."""
    from rsmm.engine import corpus
    out = []
    for rel in corpus.rels("EntitySettings/Heroes/", ".EntitySettingsResource.gen"):
        parts = rel.split("/")
        if len(parts) == 4 and parts[3] == f"{parts[2]}.entity.ot.EntitySettingsResource.gen":
            out.append(parts[2].removeprefix("Hero_"))
    return sorted(set(out) - {"Common"})


@cache
def _family(hero: str) -> dict[str, bytes]:
    """Entity stem -> bytes for every entity in the hero's folder."""
    from rsmm.engine import corpus
    folder = f"Hero_{hero}"
    out = {}
    for rel in corpus.rels(f"EntitySettings/Heroes/{folder}/", ".EntitySettingsResource.gen"):
        stem = rel.rsplit("/", 1)[-1].removesuffix(".entity.ot.EntitySettingsResource.gen")
        raw = corpus.read(rel)
        if raw is not None:
            out[stem] = raw
    return out


def _field_targets(c, f, picker_cls: int) -> list[tuple[str, str]]:
    """``(target GUID hex, target path)`` for every link in field ``f``."""
    from rsmm.engine import entity_graph as EG
    body = c.body[f.offset:f.offset + f.size]
    return [(r.guid.hex(), r.path) for _o, r in EG._pickers(body, picker_cls) if r.path]


def graph_payload(hero: str, steps: list[dict], entity: str = "") -> dict:
    """What the page draws: ``hero``'s entity after ``steps``, with issues."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG

    if hero not in _heroes():
        raise ValueError(f"no shipped hero {hero!r}")
    files = _family(hero)
    main = f"Hero_{hero}"
    stem = entity or main
    if stem not in files:
        raise ValueError(f"no entity {stem!r} in {hero}'s family")
    error, warnings = "", []
    if steps:
        try:
            res = AE.apply(files, steps, main=main, seed=f"editor:{hero}")
            files, warnings = res.files, res.warnings
        except AE.AbilityEditError as e:
            error = str(e)
    g = EG.parse(files[stem], stem)
    names = g.components[0].classes if g.components else []
    picker = names.index("oCEntityCpntPicker") if "oCEntityCpntPicker" in names else -1
    comps = []
    for c in g.components:
        fields = []
        for f in EF.fields(c):
            links = (_field_targets(c, f, picker) if f.kind in ("ref", "ref[]", "value")
                     else [])
            fields.append({
                "name": f.name, "kind": f.kind, "text": f.text,
                "targets": [g for g, _p in links], "paths": [p for _g, p in links],
                "items": len(f.items),
            })
        comps.append({"id": c.guid.hex(), "name": c.name, "group": c.group,
                      "cls": c.cls.removeprefix("oCEntityCpnt").removeprefix("oCDtEntityCpnt")
                      .removesuffix("Settings"),
                      "fields": fields})
    return {"hero": hero, "entity": stem, "entities": sorted(files),
            "components": comps, "error": error, "warnings": warnings}


def steps_toml(steps: list[dict]) -> str:
    """``steps`` as ``[[content.abilities]]`` blocks."""
    out = []
    for s in steps:
        out.append("[[content.abilities]]")
        for k, v in s.items():
            out.append(f"{k} = {json.dumps(v)}")
        out.append("")
    return "\n".join(out)


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, token: str):
        super().__init__(addr, Handler)
        self.token = token


class Handler(BaseHTTPRequestHandler):
    server: EditorServer

    def log_message(self, fmt, *args):
        pass

    def _host_ok(self) -> bool:
        # Refuse DNS-rebinding: only loopback names reach this server.
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; "
                         "style-src 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            return self._json(403, {"error": "wrong host"})
        path = urlparse(self.path).path
        if path == "/":
            from rsmm.cli.ability_editor_page import PAGE
            page = PAGE.replace("__RSMM_TOKEN__", self.server.token)
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/heroes":
            return self._json(200, {"heroes": _heroes()})
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            return self._json(403, {"error": "wrong host"})
        if self.headers.get("X-RSMM-Token") != self.server.token:
            return self._json(403, {"error": "bad token"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1 << 20:
                return self._json(413, {"error": "too large"})
            body = json.loads(self.rfile.read(n) or b"{}")
            steps = body.get("steps") or []
            if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
                return self._json(400, {"error": "steps is a list of tables"})
            path = urlparse(self.path).path
            if path == "/api/graph":
                out = graph_payload(str(body.get("hero", "")), steps,
                                    str(body.get("entity") or ""))
                out["toml"] = steps_toml(steps)
                return self._json(200, out)
            return self._json(404, {"error": "not found"})
        except (ValueError, KeyError, struct.error) as e:
            return self._json(400, {"error": str(e)})


def serve(port: int) -> EditorServer:
    return EditorServer(("127.0.0.1", port), token=secrets.token_urlsafe(24))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm ability-editor",
                                 description="see a hero's abilities as graphs and build edits")
    ap.add_argument("--port", type=int, default=8766, help="port on 127.0.0.1 (default 8766)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if not _heroes():
        print("ability-editor: no hero entities in the corpus or the game install",
              file=sys.stderr)
        return 1
    try:
        srv = serve(args.port)
    except OSError:
        srv = serve(0)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"ability editor: {url}")
    print("copy the steps into a custom hero's manifest, then: rsmm apply")
    print("Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
