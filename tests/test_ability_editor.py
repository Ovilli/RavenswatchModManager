"""`rsmm ability-editor`: the local page's server side."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from rsmm.cli import cmd_ability_editor as AE
from rsmm.engine import corpus

needs = pytest.mark.skipif(
    corpus.read("EntitySettings/Heroes/Hero_Piper/Hero_Piper.entity.ot"
                ".EntitySettingsResource.gen") is None, reason="no hero corpus")


@needs
def test_the_graph_shows_parts_fields_and_the_links_between_them():
    d = AE.graph_payload("Piper", [])
    timer = next(c for c in d["components"] if c["name"] == "Primary Ability Shoot Timer")
    on_tick = next(f for f in timer["fields"] if f["name"] == "on_tick")
    ids = {c["id"] for c in d["components"]}
    assert on_tick["targets"] and on_tick["targets"][0] in ids
    assert d["error"] == "" and "Hero_Piper_FX" in d["entities"]


@needs
def test_steps_are_applied_and_checked_before_the_graph_is_drawn():
    d = AE.graph_payload("Piper", [{"clone": "Ability Secondary", "as": "Echo"}])
    assert any(c["group"] == "Echo" for c in d["components"]) and d["error"] == ""
    bad = AE.graph_payload("Piper", [{"clone": "Ability Secondary", "as": "K", "from": "Juliet"}])
    assert "Hero_Romeo_Juliet_Common" in bad["error"]


def test_steps_render_as_manifest_toml():
    import tomllib
    steps = [{"set": "A.value", "value": 0.2}, {"link": "B.on_end", "to": ""}]
    assert tomllib.loads(AE.steps_toml(steps))["content"]["abilities"] == steps


def test_writes_need_the_token_and_every_request_a_loopback_host():
    srv = AE.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/api/graph", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
        req = urllib.request.Request(base + "/api/heroes", headers={"Host": "evil.example"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
        page = urllib.request.urlopen(base + "/").read().decode()
        assert srv.token in page and json.loads(urllib.request.urlopen(base + "/api/heroes").read())
    finally:
        srv.shutdown()
        srv.server_close()
