"""glTF -> oCAnimation cooker. The quantizers are the inverse of the preview
exporter; an exported, unedited clip must cook back byte-identically (proven on
all 2240 shipped clips when written — this keeps a sample of them honest)."""

from __future__ import annotations

import json
import math
import struct

import pytest

from rsmm.engine import anim_cook as AK
from rsmm.engine import cooked, corpus
from rsmm.engine.cooked_schemas import animation as A

DASH = "3D/Characters/Heroes/Piper/Animations/Piper_Dash_Default.fbx.Animation.gen"
needs_clip = pytest.mark.skipif(corpus.read(DASH) is None, reason="no animation corpus")


def _payload(rel=DASH) -> bytes:
    return b"".join(s.payload for s in cooked.parse(corpus.read(rel)).sections)


def _glb(nodes: list[str], channels: list[tuple[int, str, list[float], list[tuple]]]) -> bytes:
    """Minimal glTF: named nodes + LINEAR channels (node, path, times, values)."""
    binb, views, accs, samplers, chans = bytearray(), [], [], [], []

    def push(vals, typ):
        flat = [c for v in vals for c in (v if isinstance(v, tuple) else (v,))]
        data = struct.pack(f"<{len(flat)}f", *flat)
        views.append({"buffer": 0, "byteOffset": len(binb), "byteLength": len(data)})
        binb.extend(data)
        accs.append({"bufferView": len(views) - 1, "componentType": 5126,
                     "count": len(vals), "type": typ})
        return len(accs) - 1

    for node, path, times, vals in channels:
        typ = "VEC4" if path == "rotation" else "VEC3"
        samplers.append({"input": push(times, "SCALAR"), "output": push(vals, typ),
                         "interpolation": "LINEAR"})
        chans.append({"sampler": len(samplers) - 1, "target": {"node": node, "path": path}})
    doc = {"asset": {"version": "2.0"}, "nodes": [{"name": n} for n in nodes],
           "buffers": [{"byteLength": len(binb)}], "bufferViews": views, "accessors": accs,
           "animations": [{"name": "a", "samplers": samplers, "channels": chans}]}
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    binb.extend(b"\0" * (-len(binb) % 4))
    total = 12 + 8 + len(js) + 8 + len(binb)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A)
            + js + struct.pack("<II", len(binb), 0x004E4942) + bytes(binb))


def test_quantizers_invert_the_decoder():
    for v in [(0.0, 0.0, 0.0), (1.5, -2.25, 30.999), (-31.0, 0.0009765625, 7.0)]:
        assert A._decode_trans_scale(AK.quant_ts(v)) == pytest.approx(v, abs=1 / 2048)
    for q in [(0, 0, 0, 1), (0.5, -0.5, 0.5, -0.5), (0.1, 0.7, -0.2, 0.67)]:
        n = math.sqrt(sum(c * c for c in q))
        q = tuple(c / n for c in q)
        got = A._decode_quat(AK.quant_quat(q))
        assert abs(sum(a * b for a, b in zip(got, q, strict=True))) > 1 - 1e-6
    assert AK.quant_time(0.5, 1.0) == 32768 and AK.quant_time(1.0, 1.0) == 65535


@needs_clip
@pytest.mark.parametrize("rel", [
    DASH,
    "3D/Characters/Heroes/Piper/Animations/Piper_DeathDoor_In.fbx.Animation.gen",
])
def test_exported_clip_cooks_back_byte_identical(rel):
    payload = _payload(rel)
    glb = A._build_glb_preview(A.parse_payload(payload), payload)
    out, notes = AK.cook(glb, payload)
    assert out == payload and notes == []
    assert A.AnimationHandler().encode(glb) == payload   # uncook -> cook path too


@needs_clip
def test_an_edit_is_kept_and_unanimated_bones_hold_their_pose():
    tpl = A.parse_payload(_payload())
    bone = tpl.tracks[3].name
    turn = (0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4))     # 90 deg about Y
    out, notes = AK.cook(_glb([bone], [(0, "rotation", [0.0, 0.5], [(0, 0, 0, 1), turn])]),
                         _payload())
    got = A.parse_payload(out)
    tr = next(t for t in got.tracks if t.name == bone)
    assert tr.r_times == [0, 65535] and got.duration == pytest.approx(0.5)
    q = A._decode_quat(tr.r_values[1])
    assert abs(sum(a * b for a, b in zip(q, turn, strict=True))) > 1 - 1e-6
    assert [t.name for t in got.tracks] == [t.name for t in tpl.tracks]
    assert any(n.startswith(tpl.tracks[0].name) for n in notes)       # others held
    cooked.parse(cooked.emit(cooked.parse(corpus.read(DASH))))         # container still sane


@needs_clip
def test_bad_input_is_refused():
    with pytest.raises(AK.AnimCookError, match="lacks"):
        AK.cook(_glb(["NotABone"], [(0, "rotation", [0.0, 1.0], [(0, 0, 0, 1)] * 2)]),
                _payload())
    bone = A.parse_payload(_payload()).tracks[0].name
    with pytest.raises(AK.AnimCookError, match="not animated"):
        AK.cook(_glb([bone], [(0, "rotation", [0.0, 1.0], [(0, 0, 0, 1)] * 2)]),
                _payload(), strict=True)
    with pytest.raises(AK.AnimCookError, match="not a glTF"):
        AK.cook(b"nope", _payload())


@needs_clip
def test_animation_kind_writes_the_cooked_clip_over_the_target(tmp_path):
    from rsmm.sdk.content import ContentDef
    from rsmm.sdk.kinds import animations

    payload = _payload(
        "3D/Characters/Heroes/Piper/Animations/Piper_DeathDoor_In.fbx.Animation.gen")
    mod = tmp_path / "mod"
    (mod / "anims").mkdir(parents=True)
    (mod / "anims" / "x.glb").write_bytes(
        A._build_glb_preview(A.parse_payload(payload), payload))
    files = animations.emit("m", ContentDef(kind="animation", id="dash", fields={
        "target": "Characters\\Heroes\\Piper\\Animations\\Piper_Dash_Default.fbx",
        "source": "anims/x.glb"}), mod / "assets")
    assert [f.relative_to(mod / "assets").as_posix() for f in files] == [DASH]
    got = A.parse_payload(b"".join(s.payload for s in cooked.parse(files[0].read_bytes()).sections))
    assert got.duration == pytest.approx(A.parse_payload(payload).duration)
