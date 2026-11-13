"""The VFX codec (engine/vfx_codec.py): every shipped effect decodes and
re-encodes byte for byte, and the classes the codec knows are decoded into
fields (not kept raw) everywhere they appear."""

from __future__ import annotations

import collections

import pytest

from rsmm.engine import vfx_codec as V


def _effects() -> list[str]:
    from rsmm.engine import corpus
    try:
        return sorted(r for r in corpus.rels("FX/") if r.endswith(".ScheduledVfxSettings.gen"))
    except Exception:  # noqa: BLE001 — no corpus
        return []


needs_corpus = pytest.mark.skipif(not _effects(), reason="no effect corpus")

#: Classes that must decode into fields wherever they appear (the writer's set).
CORE = {"oCVisualEffectParticleSetting", "oCVfxControlCineBloc", "oC3dParticleEmitterSettings",
        "oC3dParticleEffectorSizeRampSettings", "oC3dParticleEffectorColorRampSettings",
        "oC3dParticleEffectorAlphaRampSettings", "oC3dParticleEffectorSubImageIndexSettings",
        "oC3dParticleEffectorDampingSettings", "oC3dParticleEffectorCameraOffsetSettings",
        "oI3dBillboardParticleRendererSettings"}


@needs_corpus
def test_every_shipped_effect_round_trips_and_core_classes_decode():
    from rsmm.engine import corpus
    raw_core: collections.Counter = collections.Counter()
    for rel in _effects():
        b = corpus.read(rel)
        v = V.decode(b)
        assert V.encode(v) == b, rel
        for o in v.objects:
            if o.cls in CORE and o.raw is not None:
                raw_core[o.cls] += 1
        assert v.root.fields["settings"].raw is None
        assert v.root.fields["cinematic"].raw is None
    assert not raw_core


@needs_corpus
def test_a_decoded_effect_reads_as_values():
    """The debug gizmo effect: one particle system played for a second."""
    from rsmm.engine import corpus
    v = V.decode(corpus.read("FX/Settings/FX/Common_FX/DEBUG_XYZ.vfx.ot.ScheduledVfxSettings.gen"))
    cine = v.root.fields["cinematic"].fields
    bloc = v.objects[cine["blocs"][0]].fields
    setting = v.objects[v.root.fields["settings"].fields["items"][0]]
    assert setting.cls == "oCVisualEffectParticleSetting"
    assert bloc["target"] == setting.fields["name"] and bloc["duration"] == 1.0
    eff = setting.fields["effect"].fields
    emitter = v.objects[eff["emitters"].fields["items"][0]]
    assert emitter.cls == "oC3dParticleEmitterSettings"
    assert 0 <= emitter.fields["shape"] <= 6
