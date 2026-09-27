"""`rsmm editor`: one app behind two transports.

``editor.app`` does the routing, the write token and the body rules; the HTTP
server (``rsmm editor``) and the socket-free bridge (the web editor on the docs
site) only carry requests to it. These pin that both transports get the same
answers, that each editor is reachable under its mount, and that pages stay
mountable (relative URLs only, shared CSS/JS inlined).
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from rsmm.cli.editor import abilities, app, content, server
from rsmm.cli.editor.bridge import Bridge


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(content, "heroes", lambda: ["Juliet"])
    monkeypatch.setattr(abilities, "_heroes", lambda: ["Piper"])


@pytest.fixture
def local(tmp_path, stubbed):
    srv = server.serve(0, tab="map", mods=tmp_path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def call(method, path, body=None, headers=None):
        conn = http_client(port)
        h = {"Host": f"127.0.0.1:{port}"}
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=None if body is None else json.dumps(body), headers=h)
        r = conn.getresponse()
        out = (r.status, r.read(), dict(r.getheaders()))
        conn.close()
        return out

    call.token = srv.token
    yield call
    srv.shutdown()
    srv.server_close()


def http_client(port):
    return http.client.HTTPConnection("127.0.0.1", port, timeout=10)


@pytest.fixture
def bridge(tmp_path, stubbed):
    b = Bridge(mods=tmp_path)

    def call(method, path, body=None, headers=None):
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        raw = b"" if body is None else json.dumps(body).encode()
        status, hdrs, data = b.request(method, path, raw, h)
        return status, data, hdrs

    call.token = b.token
    call.bridge = b
    return call


@pytest.fixture(params=["local", "bridge"])
def call(request):
    return request.getfixturevalue(request.param)


SAVE = {"tab": "items", "mod": "x", "create": True,
        "edit": {"base": "Dash_Crit_Chance", "id": "Dash_Crit_Chan_M", "name": "Thorn"}}


# --- the same answers over both transports -------------------------------------

@pytest.mark.parametrize("path, needle", [
    ("/content/?tab=talents", b"Item &amp; Talent Editor"),
    ("/abilities/", b"Ability Editor"),
    ("/map/", b"Map Editor"),
])
def test_each_page_is_served_whole(call, path, needle):
    status, page, headers = call("GET", path)
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert needle in page
    assert f'const TOKEN = "{call.token}"'.encode() in page            # common.js, inlined
    assert b"--accent:" in page                                       # common.css, inlined
    assert b"{{common" not in page and b"__RSMM_TOKEN__" not in page
    # Mounted under /<editor>/ locally and under <base> in the web editor, a
    # page reaches its API only through relative URLs.
    assert b'"/api/' not in page and b"`/api/" not in page and b'import("/' not in page


def test_api_calls_reach_the_right_editor(call):
    assert json.loads(call("GET", "/content/api/heroes")[1]) == {"heroes": ["Juliet"]}
    assert json.loads(call("GET", "/abilities/api/heroes")[1]) == {"heroes": ["Piper"]}


@pytest.mark.parametrize("path, body", [
    ("/content/api/save", SAVE),
    ("/abilities/api/graph", {"hero": "Piper"}),
    ("/map/api/save", {"chapter": "x", "mod_id": "x", "edits": {}}),
])
def test_every_write_demands_the_token(call, tmp_path, path, body):
    assert call("POST", path, body)[0] == 403
    assert call("POST", path, body, {"X-RSMM-Token": "wrong"})[0] == 403
    assert not (tmp_path / "x").exists()


def test_a_write_must_be_a_json_object(call):
    tok = {"X-RSMM-Token": call.token}
    assert call("POST", "/content/api/toml", "x", {**tok, "Content-Type": "text/plain"})[0] == 415
    assert call("POST", "/content/api/toml", [1], tok)[0] == 400
    status, data, _ = call("POST", "/content/api/toml", {"tab": "items"}, tok)
    assert status == 400 and "edit" in json.loads(data)["error"]


def test_a_write_with_the_token_goes_through(call, tmp_path):
    status, data, _ = call("POST", "/content/api/save", SAVE, {"X-RSMM-Token": call.token})
    assert status == 200, data
    assert (tmp_path / "x" / "manifest.toml").is_file()


def test_a_domain_error_is_a_400_with_its_reason(call):
    bad = {"tab": "items", "edit": {"base": "Dash_Crit_Chance", "id": "x"}}
    status, data, _ = call("POST", "/content/api/check", bad, {"X-RSMM-Token": call.token})
    assert status == 400 and "exactly as long" in json.loads(data)["error"]
    # The preview lists a broken edit's reason next to the blocks that do build.
    status, data, _ = call("POST", "/content/api/toml", bad, {"X-RSMM-Token": call.token})
    assert status == 200 and "exactly as long" in json.loads(data)["errors"][0]["error"]
    status, data, _ = call("GET", "/content/api/talents?hero=Nope")
    assert status == 400 and "no shipped hero" in json.loads(data)["error"]


@pytest.mark.parametrize("method, path, status", [
    ("GET", "/nope/", 404),
    ("GET", "/map/api/nope", 404),
    ("GET", "/content/api/icon?stem=..%2F..%2Fsecret", 404),
    ("GET", "/map/static/../maps.py", 404),
    ("GET", "/map", 301),
])
def test_what_is_not_there(call, method, path, status):
    assert call(method, path)[0] == status


# --- what belongs to one transport ---------------------------------------------------

def test_the_shell_lists_every_tab_and_opens_on_the_asked_one(local):
    status, page, headers = local("GET", "/")
    assert status == 200
    for key, (_label, url) in app.TABS.items():
        assert f'"{key}"'.encode() in page and url.encode() in page
    assert b'|| "map")' in page
    assert "frame-src 'self'" in headers["Content-Security-Policy"]


def test_a_foreign_host_is_refused_on_every_mount(local):
    """DNS rebinding: a page on another origin that resolves to 127.0.0.1."""
    for path in ("/", "/content/api/heroes", "/abilities/api/heroes", "/map/api/state"):
        assert local("GET", path, headers={"Host": "evil.example:80"})[0] == 403


def test_a_saved_mod_downloads_as_one_folder(bridge):
    status, data, _ = bridge("POST", "/content/api/save", SAVE,
                             {"X-RSMM-Token": bridge.token})
    assert status == 200, data
    import io
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(bridge.bridge.zip_mod("x"))).namelist()
    assert "x/manifest.toml" in names and {n.split("/", 1)[0] for n in names} == {"x"}


@pytest.mark.parametrize("mod_id", ["../escape", "missing"])
def test_only_a_saved_mod_can_be_zipped(bridge, mod_id):
    with pytest.raises(ValueError):
        bridge.bridge.zip_mod(mod_id)


def test_other_methods_are_refused(bridge):
    assert bridge("DELETE", "/content/api/items")[0] == 405


# --- commands ------------------------------------------------------------------------

@pytest.mark.parametrize("alias, tab", [("item-editor", "items"), ("talent-editor", "talents"),
                                        ("ability-editor", "abilities"), ("map-editor", "map")])
def test_the_old_commands_open_their_tab(alias, tab):
    from rsmm.cli import _dispatch
    assert _dispatch.LEGACY[alias] == ("rsmm.cli.cmd_editor", ["--tab", tab])
    assert _dispatch.BUILTIN["editor"] == "rsmm.cli.cmd_editor"
