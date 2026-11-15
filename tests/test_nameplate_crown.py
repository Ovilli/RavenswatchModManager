"""Native crown layout: real installed resources, never writes to the game."""
import struct

import pytest

from rsmm.engine import cooked, corpus, nameplate_crown as N
from rsmm.engine.entity_append import validate_layout
from rsmm.sdk.content import ContentError, ContentRegistry


@pytest.fixture
def ui_resources():
    target, source = corpus.read(N.TARGET), corpus.read(N.SOURCE)
    if target is None or source is None:
        pytest.skip("requires installed Ravenswatch UI resources")
    return target, source


def test_default_never_draws_unselected_hosts(ui_resources):
    target, source = ui_resources
    assert N.add_crown(target, source) == target


def test_appends_owned_picture_preserving_existing_objects(ui_resources):
    target, source = ui_resources
    before = cooked.parse(target)
    after = cooked.parse(N.add_crown(target, source, preview=True))
    n = validate_layout(before)
    assert validate_layout(after) == n + 1
    frame = N._find(before, N._class(before, "oC2dElementDesc", 14), N.FRAME)
    for index in range(1, len(before.sections) - 1):
        if index != frame:
            assert before.sections[index].payload == after.sections[index].payload
    assert before.sections[-1].payload == after.sections[-1].payload
    old = before.sections[frame].payload
    new = after.sections[frame].payload
    children = N._header(old)[0]
    assert N._header(new)[0] == children + 1
    assert new[49:49 + children * 4] == old[49:49 + children * 4]
    assert struct.unpack_from("<I", new, 49 + children * 4)[0] == n
    assert new[53 + children * 4:] == old[49 + children * 4:]
    picture = after.sections[-2].payload
    assert N._header(picture)[2] == N.WIDGET
    assert b"BookMenu\\LeaderPins.png" in picture
    original = cooked.parse(source)
    src = original.sections[N._find(original, N._class(original, "oC2dPictureDesc", 6), "Host_Picture")].payload
    assert picture[35:45] == src[35:45]  # flags and layer untouched


def test_repeat_requires_pristine_resource(ui_resources):
    target, source = ui_resources
    once = N.add_crown(target, source, preview=True)
    with pytest.raises(ValueError, match="already contains"):
        N.add_crown(once, source, preview=True)


@pytest.mark.parametrize("field,value", [("width", float("nan")), ("width", 100), ("y", 1), ("preview", "false")])
def test_rejects_invalid_geometry(ui_resources, field, value):
    target, source = ui_resources
    with pytest.raises(ValueError):
        N.add_crown(target, source, **({"preview": True} | {field: value}))


def test_unknown_descriptor_version_refuses_to_patch(ui_resources):
    target, source = ui_resources
    cf = cooked.parse(target)
    cf.classes[N._class(cf, "oC2dElementDesc", 14)].version_minor += 1
    with pytest.raises(ValueError, match="unsupported"):
        N.add_crown(cooked.emit(cf), source, preview=True)


def test_sdk_requires_opt_in_and_emits_native_asset(ui_resources, tmp_path):
    with pytest.raises(ContentError, match="experimental"):
        ContentRegistry("crown_test").register("nameplate_crown", id="crown", preview=True)
    registry = ContentRegistry("crown_test", experimental=True)
    registry.register("nameplate_crown", id="crown", preview=True)
    paths = registry.emit(tmp_path)
    assert paths == [tmp_path / N.TARGET]
    assert paths[0].read_bytes() == N.add_crown(*ui_resources, preview=True)
