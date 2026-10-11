"""POI `components` that inherit a marker/interaction parent on their own.

Inheriting `Minimap_Marker_Reveal_Model` (or `Interactive_Object_Model`) brings
the machinery but not the settings it reads, so the host loads, runs the state
machine, and draws no icon / offers no prompt — silently. `[marker]` and
`interactive = true` add the parent AND copy the overrides; naming the parent
alone must be refused at emit and at lint.
"""

from __future__ import annotations

import pytest

from rsmm.cli import lint
from rsmm.engine import entity_components as EC
from rsmm.sdk.kinds import poi

_REVEAL = EC.OVERRIDE_DONORS["minimap"][0]


@pytest.mark.parametrize("prop, inert", [
    ({"components": ["minimap"]}, 1),
    ({"components": ["interaction"]}, 1),
    ({"components": [_REVEAL]}, 1),                       # literal ref, same parent
    ({"components": ["minimap", "interaction"]}, 2),
    ({"components": ["minimap"], "marker": {"icon": "a.png"}}, 0),
    ({"components": ["interaction"], "interactive": True}, 0),
    ({"components": ["Objects\\Some\\Other_Model.entity.ot"]}, 0),
    ({}, 0),
])
def test_inert_components(prop, inert):
    assert len(poi.inert_components(prop)) == inert


def test_message_names_the_fix():
    (why,) = poi.inert_components({"components": ["minimap"]})
    assert "[marker]" in why and "does nothing" in why


def test_lint_fails_a_bare_marker_parent(tmp_path, capsys):
    blocks = [{"kind": "poi", "id": "shrine", "prop": {"components": ["minimap"]}},
              {"kind": "poi", "id": "fine",
               "prop": {"components": ["interaction"], "interactive": True}}]
    assert lint._lint_poi_components("M", tmp_path, blocks) == 1
    out = capsys.readouterr().out
    assert "shrine" in out and "fine" not in out
