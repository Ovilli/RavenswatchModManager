"""The `skill` kind's `icon` field: cook a mod PNG over a slot's own icon.

The slot's icon is resolved from the hero ENTITY (the first `.png` path after
the controller's name) rather than guessed from the name, because icon files do
not follow controller names: Red's `Secondary Quick Bombs` draws
`Skill Special Quick Bombs.png`.
"""

from pathlib import Path

import pytest

from rsmm.engine import cooked, image
from rsmm.engine.cooked_schemas import texture as T
from rsmm.sdk.content import ContentError
from rsmm.sdk.kinds import skills

_RED = (Path(__file__).resolve().parents[1] / "data" / "uncooked" / "EntitySettings"
        / "Heroes" / "Hero_Red" / "Hero_Red.entity.ot.EntitySettingsResource.gen")


def test_scale_keeps_colour_and_premultiplies_alpha():
    # 4x4: left half opaque orange, right half fully transparent BLACK. A naive
    # average would drag the edge towards dark; premultiplied does not.
    px = b""
    for _y in range(4):
        px += bytes([255, 120, 0, 255]) * 2 + bytes([0, 0, 0, 0]) * 2
    out = skills._scale_rgba(4, 4, px, 2, 2)
    assert out[0:4] == bytes([255, 120, 0, 255])     # opaque orange survives
    assert out[4:8][3] == 0                          # transparent stays clear


def test_slot_icon_is_read_from_the_entity_not_the_name():
    if not _RED.is_file():
        pytest.skip("Red entity not present")
    assert (skills._slot_icon_texture("Red", "Secondary Quick Bombs")
            == "Ui/Heroes/Red/Skill Special Quick Bombs.png.Texture.dxt")
    # bank-style casing of the hero token resolves too
    assert skills._slot_icon_texture("RED", "Skill Controller Primary Bleed").startswith(
        "Ui/Heroes/Red/")


def test_unknown_controller_names_what_it_missed():
    if not _RED.is_file():
        pytest.skip("Red entity not present")
    with pytest.raises(ContentError, match="Nonexistent"):
        skills._slot_icon_texture("Red", "Primary Nonexistent")


def test_emit_icon_writes_the_slot_texture_in_its_true_colours(tmp_path):
    if not _RED.is_file():
        pytest.skip("Red entity not present")
    mod = tmp_path / "mod"
    (mod / "art").mkdir(parents=True)
    # 192x192 orange: not the vanilla size, so it must be scaled to 128x128
    (mod / "art" / "icon.png").write_bytes(
        image.encode_png(192, 192, bytes([255, 120, 0, 255]) * (192 * 192)))
    out = mod / "assets"
    [dest] = skills._emit_icon("Red", "Secondary Quick Bombs", "art/icon.png", mod, out)
    assert dest == out / "Ui" / "Heroes" / "Red" / "Skill Special Quick Bombs.png.Texture.dxt"
    schema = T._decode_payload(cooked.parse(dest.read_bytes()).sections[-1].payload)
    assert (schema.width, schema.height) == (128, 128)
    # stored pixels, not a decoder round trip: the decoder swaps R/B itself
    assert tuple(schema.pixels[0:4]) == (255, 120, 0, 255)


def test_emit_icon_rejects_a_missing_or_non_png_file(tmp_path):
    if not _RED.is_file():
        pytest.skip("Red entity not present")
    (tmp_path / "art").mkdir()
    (tmp_path / "art" / "icon.jpg").write_bytes(b"not a png")
    for icon in ("art/icon.jpg", "art/missing.png"):
        with pytest.raises(ContentError, match="not a PNG"):
            skills._emit_icon("Red", "Secondary Quick Bombs", icon, tmp_path, tmp_path / "a")
