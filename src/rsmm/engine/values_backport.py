"""Turn a values snapshot into a mod that plays that older patch's data.

The exe cannot be rolled back, but its data can: the serializer reads every
historical class version (a patch leaves hundreds of files at older versions
and the new exe loads them), so the snapshot's cooked bytes are valid input to
the current build. What a later patch did to the data falls into four groups,
each rolled back differently:

* **files changed in place** -> the snapshot's bytes, as whole-file overrides.
* **herodefs**, which a content update re-ships under a new name and deletes
  (Update 6: ``Piper.herodef.ot`` -> ``Piper_Update6.herodef.ot``): the old
  content written under the CURRENT name, because the exe and the versiondef
  name the current one. References to other herodefs inside are renamed too.
* **the LiveOps versiondef**, same story (``LiveOps5`` -> ``LiveOps6``): the
  old content under the current name. Its alias-override table is what wires
  each ``Hero_<X>_Update6`` rework entity over the base entity, so the old
  table (Update 5: only ``Hero_Common_Update5``) is what turns the reworks off.
  Heroes the old patch did not have (Kintaro) are appended to its hero vector
  so they stay playable, through the same splice ``apply`` uses for mod heroes.
* **files renamed** (Update 6: ``40x40_Storm_Island_Thieves_*`` tiles became
  ``40x40_SI_Thieves_*``, and the restored Storm Island mapdef names the old
  spelling): references in the restored files are rewritten to the current
  name, like the herodefs. The old copy is not re-added: its level and resource
  cache are outside the snapshot, and a tile without them is a crash risk.
* **files removed** -> re-added at their old path only when some restored file
  still references them; one that nothing points at would just be an orphan.

Files the later patch ADDED are left alone: with the references above rolled
back nothing reaches them, except what is kept on purpose (a new hero).

The result is local game data. It must never be committed or published
(``mods/`` is untracked for that reason); :func:`build` writes it there, with
a :data:`MARKER` file that ``rsmm pack`` (and so ``rsmm publish``) refuses.
"""

from __future__ import annotations

import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from . import entity_strings as ES
from . import herodefs
from . import values_snapshot as VS
from . import versiondef as VD

_HERODEF_DIR = herodefs.HERODEF_DIR + "/"
_VERSIONS_DIR = "Definitions/Versions/"
_HERODEF_REF = re.compile(r"^Heroes\\(.+)\.herodef\.ot$")


#: Dropped in every generated mod; `rsmm pack` refuses a mod that has it. The
#: vanilla-bytes check cannot catch a backport: its files are the OLDER patch's
#: originals, which match nothing the current install ships.
MARKER = "BACKPORT_LOCAL_ONLY"


class BackportError(RuntimeError):
    pass


@dataclass
class Report:
    mod_dir: Path
    changed: list[str] = field(default_factory=list)
    herodefs: list[tuple[str, str]] = field(default_factory=list)   # (old, current)
    versiondef: tuple[str, str] | None = None
    readded: list[str] = field(default_factory=list)
    kept_heroes: list[str] = field(default_factory=list)
    skipped_removed: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)   # (old, current)


def _snapshot_files(ref: str) -> dict[str, bytes]:
    path = VS.resolve(ref) / "cooked.tar.gz"
    if not path.is_file():
        raise BackportError(f"snapshot {ref!r} has no cooked.tar.gz")
    out: dict[str, bytes] = {}
    with tarfile.open(path) as tar:
        for m in tar:
            f = tar.extractfile(m) if m.isfile() else None
            if f is not None:
                out[m.name] = f.read()
    return out


def _stem_of(rel: str, suffix: str) -> str:
    return rel.rsplit("/", 1)[-1][: -len(suffix)]


def _ref_form(rel: str) -> str:
    """How cooked data names a file: ``Definitions/Tiles/A/x.tiledef.ot.DtTile
    Definition.gen`` -> ``Tiles\\A\\x.tiledef.ot``."""
    body = rel.split("/", 1)[-1]
    return body[: body.rindex(".ot.") + 3].replace("/", "\\")


def _renames(removed: list[str], added: list[str]) -> dict[str, str]:
    """Removed file -> the added file it became: same directory and kind, and
    the one clearly closest name (difflib ratio >= 0.8, no tie)."""
    import difflib

    def split(rel: str) -> tuple[str, str, str]:
        d, leaf = rel.rsplit("/", 1)
        i = leaf.index(".")
        return d, leaf[:i], leaf[i:]

    out: dict[str, str] = {}
    for r in removed:
        d, name, kind = split(r)
        scored = sorted(((difflib.SequenceMatcher(None, name, split(a)[1]).ratio(), a)
                         for a in added if split(a)[0] == d and split(a)[2] == kind),
                        reverse=True)
        if scored and scored[0][0] >= 0.8 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            out[r] = scored[0][1]
    return out


def build(ref: str, mod_dir: Path, *, mod_id: str, force: bool = False) -> Report:
    """Write a mod at ``mod_dir`` that restores snapshot ``ref``'s data."""
    if mod_dir.exists() and not force:
        raise BackportError(f"{mod_dir} already exists (pass force to overwrite)")
    old = _snapshot_files(ref)
    read, rels = VS._install_reader()
    current: set[str] = set()
    for prefix in VS.RAW_PREFIXES:
        current.update(rels(prefix))

    # Old herodef stem -> current stem, by hero name.
    now = herodefs.stems()
    rename: dict[str, str] = {}
    for rel in old:
        if rel.startswith(_HERODEF_DIR) and rel.endswith(herodefs.HERODEF_SUFFIX):
            stem = _stem_of(rel, herodefs.HERODEF_SUFFIX)
            cur = now.get(herodefs.hero_name(stem))
            if cur is None:
                raise BackportError(f"hero {stem!r} from the snapshot no longer ships")
            rename[stem] = cur

    vd_suffix = ".versiondef.ot.rsionDefinition.gen"
    old_vd = [r for r in old if r.startswith(_VERSIONS_DIR) and r.endswith(vd_suffix)]
    if len(old_vd) != 1:
        raise BackportError(f"expected one versiondef in the snapshot, found {old_vd}")
    handled = {f"{_HERODEF_DIR}{s}{herodefs.HERODEF_SUFFIX}" for s in rename} | {old_vd[0]}
    removed = [r for r in sorted(old) if r not in current and r not in handled]
    moved = _renames(removed, sorted(current - set(old)))
    by_ref = {_ref_form(a): _ref_form(b) for a, b in moved.items()}
    needles = [n.encode("latin1") for n in by_ref] + [b".herodef.ot"]

    def fix(s: str) -> str:
        m = _HERODEF_REF.match(s)
        if m and m[1] in rename:
            return f"Heroes\\{rename[m[1]]}.herodef.ot"
        return by_ref.get(s, s)

    def renamed(raw: bytes) -> bytes:
        return ES.rewrite_strings(raw, fix)[0] if any(n in raw for n in needles) else raw

    report = Report(mod_dir)
    out: dict[str, bytes] = {}

    # Herodefs: old content, current name.
    for stem, cur in sorted(rename.items()):
        out[f"{_HERODEF_DIR}{cur}{herodefs.HERODEF_SUFFIX}"] = renamed(
            old[f"{_HERODEF_DIR}{stem}{herodefs.HERODEF_SUFFIX}"])
        report.herodefs.append((stem, cur))

    # The versiondef: old content under the name the exe loads.
    vd = renamed(old[old_vd[0]])
    extra = sorted(set(now) - {herodefs.hero_name(s) for s in rename})
    if extra:
        patched = VD._patch_versiondef_heroes(
            vd, [f"Heroes\\{now[h]}.herodef.ot" for h in extra])
        if patched is None:
            raise BackportError("the snapshot's versiondef has no hero vector to keep "
                                f"{', '.join(extra)} in")
        vd = patched
        report.kept_heroes = extra
    vd_rel = _VERSIONS_DIR + VD.VERSIONDEF_GEN_LEAF
    if vd_rel not in current:
        raise BackportError(f"the install has no {vd_rel}")
    out[vd_rel] = vd
    report.versiondef = (old_vd[0].rsplit("/", 1)[-1], VD.VERSIONDEF_GEN_LEAF)

    # Files changed in place. One the later patch left byte-identical is left
    # alone even when it names a renamed file: that is how the current game
    # ships it (Update 6's memoir achievements still say `Aladdin.herodef.ot`).
    for rel in sorted(old):
        if rel in handled or rel not in current:
            continue
        cur = read(rel)
        want = renamed(old[rel]) if cur != old[rel] else cur
        if want == cur:            # unchanged, or only renamed back to today's bytes
            continue
        out[rel] = want
        report.changed.append(rel)
    report.renamed = sorted(moved.items())

    # Files removed since: only those the restored data still points at.
    gone = [r for r in removed if r not in moved]
    blob = b"\0".join(out.values())
    for rel in gone:
        if _ref_form(rel).encode("latin1") in blob:
            out[rel] = renamed(old[rel])
            report.readded.append(rel)
        else:
            report.skipped_removed.append(rel)

    _write(mod_dir, mod_id, ref, out, report)
    return report


def _write(mod_dir: Path, mod_id: str, ref: str, files: dict[str, bytes],
           report: Report) -> None:
    import shutil
    if mod_dir.exists():
        shutil.rmtree(mod_dir)
    for rel, raw in files.items():
        dest = mod_dir / "assets" / Path(*rel.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    kept = (f" Heroes the snapshot did not have stay playable: "
            f"{', '.join(report.kept_heroes)}." if report.kept_heroes else "")
    (mod_dir / MARKER).write_text(
        f"Generated by `rsmm values backport {ref}`. Every file under assets/ is the\n"
        "game's own data from an older patch. Keep it on this machine: `rsmm pack`\n"
        "and `rsmm publish` refuse a mod that has this file.\n", encoding="utf-8")
    (mod_dir / "manifest.toml").write_text(
        "[mod]\n"
        f'id          = "{mod_id}"\n'
        f'name        = "Backport: {ref}"\n'
        'version     = "1.0.0"\n'
        'author      = "rsmm values backport"\n'
        f'summary     = "Plays the game data of snapshot {ref} on the current game build."\n'
        f'description = "Generated by `rsmm values backport {ref}`: {len(report.changed)} '
        f"changed file(s), {len(report.herodefs)} herodef(s) and the LiveOps versiondef "
        f'restored, {len(report.readded)} removed file(s) re-added.{kept} Local only: '
        f'it is the game\'s own data, never publish it."\n'
        'sdk_version = "3"\n'
        "enabled     = false\n"
        'tags        = ["backport", "balance"]\n'
        "# Every player must run it: the data decides gameplay for the whole party.\n"
        'multiplayer_scope = "deterministic-shared"\n',
        encoding="utf-8")
