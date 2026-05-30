"""Stage 5e — oCSkeleton bone-count scanner.

Pure structural test against a synthetic payload that mimics the
on-disk layout (top-level BEGIN/END per bone). No game install
required.
"""

from __future__ import annotations

from rsmm.engine.cooked_schemas.skeleton import (
    MARK_BEGIN,
    MARK_END,
    SkeletonHandler,
    count_bone_subobjects,
)


def _bone(payload: bytes = b"\0" * 16) -> bytes:
    return MARK_BEGIN + payload + MARK_END


def test_empty_payload_zero_bones() -> None:
    assert count_bone_subobjects(b"") == 0


def test_three_flat_bones() -> None:
    payload = _bone() + _bone() + _bone()
    assert count_bone_subobjects(payload) == 3


def test_nested_sub_subobjects_do_not_double_count() -> None:
    nested = MARK_BEGIN + b"\0" * 8 + _bone() + MARK_END
    assert count_bone_subobjects(nested + _bone()) == 2


def test_handler_registered() -> None:
    from rsmm.engine import cooked_schemas

    h = cooked_schemas.get("oCSkeleton")
    assert isinstance(h, SkeletonHandler)
    assert h.bone_count(_bone() + _bone()) == 2
