"""Custom **challenge** content builder — a new entry on the challenge screen.

A challenge is a named bundle of up to five game modifiers (DodgeIt = Dash Low
Cooldown + Less Healing + Stronger Low Life Enemies). ``emit()`` clones a
retail ``.challengedef.ot`` (:mod:`rsmm.engine.challenge_cook`), gives it its
own title key, modifier list and GUID, and writes its preload cache.
``apply`` registers it in ``UsedRscList``; the challenge page lists every
loaded ChallengeDefinition (Ghidra, FUN_140423290), so nothing else is edited.

The shipped text bank also titles three challenges that never got a def —
``AllIn``, ``TeamUp`` and ``TheCrucible`` — so an id of one of those keeps its
retail title without a ``name``.

Fields:
    ``modifiers`` (list, required)  1-5 shipped modifier ids (their filename
                                    stems, e.g. ``NoMinimap``), slot order.
    ``name`` (str)                  display title (``Challenge_<id>_Title``);
                                    required unless the bank already has it.
    ``base`` (str, default DodgeIt) retail challenge to clone.

Confidence: ``guess`` — cooks byte-exact, appearing in game is unproven.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from ...engine import challenge_cook as CK
from ...engine import corpus
from ...engine import rsc_cache as RC
from ...engine import text_patches as TP
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C
from .modifiers import _TEXT_BANK_DECODED, _bank_prior, _install_bank, _write_bank_files

_log = logging.getLogger(__name__)

_DIR = "Definitions/Challenges"
_MOD_DIR = "Definitions/GameModifiers"
_MOD_SUFFIX = ".gamemodifierdef.ot.meModifierDefinition.gen"
#: Namespace for challenge GUIDs: a clone must not share its base's identity.
_GUID_NS = uuid.UUID("6f1c6c1e-9b0e-4c55-9a4e-2f2a3d0c5e11")


def _modifiers(defn: ContentDef) -> list[str]:
    raw = defn.fields.get("modifiers")
    if not isinstance(raw, list) or not raw or not all(isinstance(m, str) and m for m in raw):
        raise ContentError(f"challenge {defn.id}: modifiers must be a list of 1-{CK.SLOTS} "
                           "shipped modifier ids, e.g. [\"NoMinimap\", \"DayOnly\"]")
    if len(raw) > CK.SLOTS:
        raise ContentError(f"challenge {defn.id}: a challenge holds at most {CK.SLOTS} "
                           f"modifiers (got {len(raw)})")
    if len(set(raw)) != len(raw):
        raise ContentError(f"challenge {defn.id}: a modifier is listed twice")
    missing = [m for m in raw if not corpus.exists(f"{_MOD_DIR}/{m}{_MOD_SUFFIX}")]
    if missing:
        raise ContentError(f"challenge {defn.id}: not a shipped modifier: {', '.join(missing)}")
    return raw


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one challenge def, its preload cache and its title."""
    C.validate_id("challenge", defn.id)
    mods = _modifiers(defn)
    base = defn.fields.get("base") or "DodgeIt"
    base_bytes = corpus.read(f"{_DIR}/{base}{CK.GEN_SUFFIX}")
    if base_bytes is None:
        raise SchemaNotMined(f"challenge {defn.id}: base {base!r} is not a shipped challenge "
                             "(the game install, or data/uncooked, must be readable)")

    key = f"Challenge_{defn.id}_Title"
    name = defn.fields.get("name")
    written: list[Path] = []
    if name is not None:
        bank = _install_bank()
        if bank is None:
            raise SchemaNotMined(f"challenge {defn.id}: the challenge text bank is not in the "
                                 "game install, so the title can't be set")
        files, _rows = TP.patch_bank(bank, {key: str(name)}, _bank_prior(out_dir))
        written += _write_bank_files(files, out_dir)
    else:
        keys = TP.parse_text_bytes(corpus.read(_TEXT_BANK_DECODED), None).entries
        if key not in keys:
            raise ContentError(f"challenge {defn.id}: needs a 'name' — the text bank has no "
                               f"{key}")

    guid = uuid.uuid5(_GUID_NS, f"{mod_id}:{defn.id}").bytes
    try:
        cooked_bytes = CK.clone(base_bytes, title_key=key, modifiers=mods, guid=guid)
    except CK.ChallengeCookError as e:
        raise ContentError(f"challenge {defn.id}: {e}") from e
    rel = f"{_DIR}/{defn.id}{CK.GEN_SUFFIX}"
    dest = out_dir / Path(*rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(cooked_bytes)
    written.append(dest)

    # Its own line plus each modifier's closure (def, text bank, icon) — what
    # every shipped challenge cache is. Sorted: the engine binary-searches it.
    lines = {RC.entry_for(rel)}
    for m in mods:
        blob = corpus.read(RC.cache_path_for(f"{_MOD_DIR}/{m}{_MOD_SUFFIX}"))
        if blob is None:
            raise SchemaNotMined(f"challenge {defn.id}: modifier {m!r} has no resource cache")
        lines |= set(RC.parse(blob))
    cache = out_dir / Path(*RC.cache_path_for(rel).split("/"))
    cache.write_bytes(RC.render(sorted(lines)))
    written.append(cache)

    _log.info("challenge %s/%s: %s (base %s)", mod_id, defn.id, ", ".join(mods), base)
    return written
