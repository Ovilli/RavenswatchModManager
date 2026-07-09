"""Entity inspection helpers for cooked Ravenswatch UI assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import cooked
from . import entity_strings as ES


@dataclass(frozen=True)
class EntitySummary:
    path: str = ""
    variant: str = ""
    classes: tuple[cooked.ClassDef, ...] = ()
    section_sizes: tuple[int, ...] = ()
    strings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityDiff:
    left: EntitySummary
    right: EntitySummary
    same_variant: bool
    same_classes: bool
    same_section_sizes: bool
    only_left_strings: tuple[str, ...]
    only_right_strings: tuple[str, ...]


def _unique_strings(cooked_bytes: bytes) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for _, _, s in ES.list_strings(cooked_bytes):
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return tuple(out)


def summarize_entity(cooked_bytes: bytes, *, path: str = "") -> EntitySummary:
    cf = cooked.parse(cooked_bytes)
    return EntitySummary(
        path=path,
        variant=cf.variant,
        classes=tuple(cf.classes),
        section_sizes=tuple(len(sec.payload) for sec in cf.sections),
        strings=_unique_strings(cooked_bytes),
    )


def diff_entities(left: bytes, right: bytes, *, left_path: str = "",
                  right_path: str = "") -> EntityDiff:
    a = summarize_entity(left, path=left_path)
    b = summarize_entity(right, path=right_path)
    left_strings = set(a.strings)
    right_strings = set(b.strings)
    return EntityDiff(
        left=a,
        right=b,
        same_variant=a.variant == b.variant,
        same_classes=a.classes == b.classes,
        same_section_sizes=a.section_sizes == b.section_sizes,
        only_left_strings=tuple(s for s in a.strings if s not in right_strings),
        only_right_strings=tuple(s for s in b.strings if s not in left_strings),
    )


def format_summary(summary: EntitySummary, *, max_strings: int = 12) -> list[str]:
    out = [
        f"{summary.path or '<entity>'}: variant={summary.variant or '?'}",
        f"  sections: {len(summary.section_sizes)} "
        f"({', '.join(str(n) for n in summary.section_sizes) or 'none'})",
        f"  classes: {len(summary.classes)}",
    ]
    for cls in summary.classes:
        out.append(
            f"    - {cls.name} "
            f"(id={cls.class_id:#x}, v={cls.version_major}.{cls.version_minor}, "
            f"parent={cls.parent_id:#x})"
        )
    out.append(f"  strings: {len(summary.strings)}")
    for s in summary.strings[:max_strings]:
        out.append(f"    - {s}")
    if len(summary.strings) > max_strings:
        out.append(f"    ... {len(summary.strings) - max_strings} more")
    return out


def format_diff(diff: EntityDiff, *, max_strings: int = 10) -> list[str]:
    out = [
        "left:",
        *format_summary(diff.left, max_strings=max_strings),
        "right:",
        *format_summary(diff.right, max_strings=max_strings),
        "diff:",
        f"  same_variant: {'yes' if diff.same_variant else 'no'}",
        f"  same_classes: {'yes' if diff.same_classes else 'no'}",
        f"  same_section_sizes: {'yes' if diff.same_section_sizes else 'no'}",
        f"  only_left_strings: {len(diff.only_left_strings)}",
    ]
    for s in diff.only_left_strings[:max_strings]:
        out.append(f"    - {s}")
    if len(diff.only_left_strings) > max_strings:
        out.append(f"    ... {len(diff.only_left_strings) - max_strings} more")
    out.append(f"  only_right_strings: {len(diff.only_right_strings)}")
    for s in diff.only_right_strings[:max_strings]:
        out.append(f"    - {s}")
    if len(diff.only_right_strings) > max_strings:
        out.append(f"    ... {len(diff.only_right_strings) - max_strings} more")
    return out


def _pristine(path: Path) -> Path:
    bak = path.with_name(path.name + ".rsmm.bak")
    return bak if bak.is_file() else path


def load_entity_asset(cooking_root: Path, dec2enc: dict[str, str], decoded: str,
                      *, pristine: bool = True) -> tuple[Path, bytes]:
    dec = decoded.replace("\\", "/")
    enc = dec2enc.get(dec)
    if not enc:
        raise ValueError(f"asset map is missing {dec!r}")
    path = cooking_root / Path(*enc.replace("\\", "/").split("/"))
    if pristine:
        path = _pristine(path)
    if not path.is_file():
        raise FileNotFoundError(f"cooked file not found: {path}")
    return path, path.read_bytes()
