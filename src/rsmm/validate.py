"""
Static validation for SDK-authored mods.

Surfaces typos and missing assets at *build* time (when the modder runs
`python3 build.py`) instead of at *apply* time (when `./rsmm apply`
discovers the patch can't be applied to anything).

Public surface:

    validate_mod(mod_state, *, asset_map_path=None) -> list[ValidationError]
    format_errors(errors) -> str
    ValidationError                 (dataclass)

The validator is deliberately decoupled from `sdk.Mod`: it accepts any
object exposing a `patches` attribute that iterates objects with
`.kind: str` and `.args: dict`. The SDK's `_Patch` dataclass satisfies
this; ad-hoc test doubles can too.

What is checked:

  * stat name      — must appear in the asset_map's stat catalog
                     (GlobalEntityValueSettings / meModifierDefinition /
                     DtEnemyCampDifficultyDefinition leaves).
  * texture        — target *and* donor decoded paths must exist in
                     the asset map. Friendly aliases must have already
                     been resolved (the SDK does that in `_resolve_texture`).
  * text bank/lang — bank short-name must match a `Text\<Bank>~GAM.xls.LocalText.gen`
                     entry; lang must be one of the cipher-mapped codes
                     (or "ALL"). Key existence requires a live game
                     install and is left to apply-time.
  * url field      — must be one of the four known menu URL slots in
                     ApplicationSettings.ot.

Each problem becomes one `ValidationError`. Suggestions come from
`difflib.get_close_matches` over the relevant catalog (capped to one
suggestion per error to keep messages skim-able).
"""

from __future__ import annotations

import csv
import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


# --- error model ----------------------------------------------------------


@dataclass
class ValidationError:
    """One validation problem. Not raised — collected into a list and
    surfaced together so the modder fixes everything in one shot.

    Attributes:
        kind: short machine tag, e.g. "unknown_stat", "missing_texture".
        verb: the SDK call this came from: "stat" | "texture" | "text" | "url".
        name: the offending name/path as the modder wrote it.
        message: human-readable description.
        suggestion: nearest valid name (fuzzy match) or None.
    """
    kind: str
    verb: str
    name: str
    message: str
    suggestion: Optional[str] = None


# --- known fixed catalogs -------------------------------------------------


# Mirrors KNOWN_KEYS in src/rsmm/cli/make_url_mod.py. Kept in sync by hand;
# if a new URL slot is RE'd into ApplicationSettings.ot, add it both places.
KNOWN_URL_FIELDS: frozenset[str] = frozenset({
    "DiscordUrl", "PatchNoteUrl", "BugReportsUrl",
    "NewUpdateUrl", "SignToolDescUrl",
})


# Mirrors DECODED_TO_ENCODED_LANG in src/rsmm/cli/make_text_mod.py, plus the
# special "ALL" pseudo-language the SDK accepts (broadcasts to every locale).
KNOWN_TEXT_LANGS: frozenset[str] = frozenset({
    "EN", "JA", "KO", "RU", "ES", "DE", "PL", "FR", "IT",
    "PT-BR", "ZH-S", "ZH-T", "RAW", "ALL",
})


# Decoded-path substrings that mark a stat-bearing cooked file. Mirrors
# the discriminator in sdk.Mod.validate(); kept independent so we never
# import sdk.py back here (avoids cycles when validate is called *from*
# sdk).
_STAT_SUFFIXES: tuple[str, ...] = (
    ".globalvalue.ot.GlobalEntityValueSettings.gen",
    ".gamemodifierdef.ot.meModifierDefinition.gen",
    ".enemycampdifficultydef.ot.DtEnemyCampDifficultyDefinition.gen",
)


# --- catalog loading ------------------------------------------------------


@dataclass
class _Catalog:
    """Indexed view of asset_map relevant to SDK validation."""
    # Decoded path (forward-slash) -> encoded. Exactly what
    # rsmm.engine.asset_map.decoded_to_encoded() produces, but loaded
    # without forcing a project-root resolve (so tests can inject a
    # tiny fixture map via `asset_map_path=`).
    decoded_to_encoded: dict[str, str] = field(default_factory=dict)
    # Lower-cased stat leaf name -> original-case name (first wins). Used
    # for both presence checks and case-preserving suggestions.
    stat_names: dict[str, str] = field(default_factory=dict)
    # Bank short-name (case-preserved) -> True. set-of-strings via a dict
    # for fast `in` and predictable iteration order.
    text_banks: dict[str, bool] = field(default_factory=dict)


def _default_asset_map_path() -> Path:
    """Locate `data/asset_map.json` without importing engine.paths.

    Keeps `validate.py` runnable in test harnesses that haven't set up
    the engine module's import-time `_find_repo_root` walk.
    """
    here = Path(__file__).resolve()
    for cand in [here.parent, *here.parents]:
        p = cand / "data" / "asset_map.json"
        if p.exists():
            return p
    # Last-ditch: 4 levels up matches `src/rsmm/validate.py` -> repo root.
    return here.parents[3] / "data" / "asset_map.json"


def _load_asset_map(path: Path) -> dict[str, str]:
    """Load asset_map.json *or* asset_map.csv into encoded->decoded dict.

    CSV is supported so tiny test fixtures can be 2-line files.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        out: dict[str, str] = {}
        reader = csv.reader(text.splitlines())
        header = next(reader, None)
        # Header is "Obfuscated Path,Decrypted Path" in the real file.
        # If a fixture omits the header line, fall through and treat
        # the first row as data.
        if header and (header[0].lower().startswith("obfuscated")
                       or header[0].lower().startswith("encoded")):
            pass
        else:
            if header and len(header) >= 2:
                out[header[0]] = header[1]
        for row in reader:
            if len(row) >= 2:
                out[row[0]] = row[1]
        return out
    return json.loads(text)


def _build_catalog(asset_map_path: Optional[Path]) -> _Catalog:
    path = asset_map_path or _default_asset_map_path()
    enc_to_dec = _load_asset_map(path)
    dec_to_enc: dict[str, str] = {
        v.replace("\\", "/"): k for k, v in enc_to_dec.items()
    }

    cat = _Catalog(decoded_to_encoded=dec_to_enc)

    for dec_norm in dec_to_enc:
        # stat catalog: leaf-before-first-dot of any stat-bearing cooked file
        if any(suf in dec_norm for suf in _STAT_SUFFIXES):
            leaf = dec_norm.rsplit("/", 1)[-1].split(".", 1)[0]
            cat.stat_names.setdefault(leaf.lower(), leaf)
        # text bank catalog: Text/<Bank>~GAM.xls.LocalText.gen
        if dec_norm.endswith(".LocalText.gen"):
            leaf = dec_norm.rsplit("/", 1)[-1]
            short = leaf.split("~", 1)[0]
            if short:
                cat.text_banks.setdefault(short, True)

    return cat


# --- suggestion helper ----------------------------------------------------


def _suggest(needle: str, haystack: Iterable[str]) -> Optional[str]:
    """One nearest-match suggestion, or None if nothing is close enough."""
    matches = difflib.get_close_matches(needle, list(haystack), n=1, cutoff=0.6)
    return matches[0] if matches else None


# --- per-verb checks ------------------------------------------------------


def _check_stat(args: dict, cat: _Catalog) -> list[ValidationError]:
    name = args.get("name")
    if not isinstance(name, str) or not name:
        return [ValidationError(
            kind="missing_name", verb="stat", name=str(name),
            message="stat() requires a non-empty `name` argument",
        )]
    if name.lower() in cat.stat_names:
        return []
    suggestion = _suggest(name, cat.stat_names.values())
    msg = f"unknown stat name {name!r} (not in asset_map stat catalog)"
    return [ValidationError(
        kind="unknown_stat", verb="stat", name=name,
        message=msg, suggestion=suggestion,
    )]


def _check_texture(args: dict, cat: _Catalog) -> list[ValidationError]:
    errs: list[ValidationError] = []
    for side in ("target", "donor"):
        path = args.get(side)
        if not isinstance(path, str) or not path:
            errs.append(ValidationError(
                kind="missing_texture_side", verb="texture", name=str(path),
                message=f"texture() requires `{side}` to be a non-empty path",
            ))
            continue
        norm = path.replace("\\", "/")
        if norm in cat.decoded_to_encoded:
            continue
        suggestion = _suggest(norm, cat.decoded_to_encoded.keys())
        errs.append(ValidationError(
            kind="missing_texture", verb="texture", name=path,
            message=f"texture {side} path not found in asset_map: {path!r}",
            suggestion=suggestion,
        ))
    return errs


def _check_text(args: dict, cat: _Catalog) -> list[ValidationError]:
    errs: list[ValidationError] = []
    bank = args.get("bank")
    lang = args.get("lang")
    key = args.get("key")

    if not isinstance(bank, str) or not bank:
        errs.append(ValidationError(
            kind="missing_bank", verb="text", name=str(bank),
            message="text() requires a non-empty `bank`",
        ))
    elif bank not in cat.text_banks:
        # case-insensitive fallback (CLI accepts it too)
        ci_hit = next((b for b in cat.text_banks
                       if b.lower() == bank.lower()), None)
        if ci_hit is None:
            errs.append(ValidationError(
                kind="unknown_text_bank", verb="text", name=bank,
                message=f"unknown text bank {bank!r}",
                suggestion=_suggest(bank, cat.text_banks.keys()),
            ))

    if not isinstance(lang, str) or not lang:
        errs.append(ValidationError(
            kind="missing_lang", verb="text", name=str(lang),
            message="text() requires a `lang` (use 'ALL' for every locale)",
        ))
    elif lang.upper() not in KNOWN_TEXT_LANGS:
        errs.append(ValidationError(
            kind="unknown_lang", verb="text", name=lang,
            message=f"unknown lang code {lang!r}",
            suggestion=_suggest(lang.upper(), KNOWN_TEXT_LANGS),
        ))

    if not isinstance(key, str) or not key:
        errs.append(ValidationError(
            kind="missing_key", verb="text", name=str(key),
            message="text() requires a non-empty `key`",
        ))
    # NOTE: per-key existence requires reading the live game's parsed
    # text bank (see make_text_mod.parse_text_file). The asset_map alone
    # doesn't carry string indices, so key validity is enforced at
    # apply-time, not here.

    return errs


def _check_url(args: dict) -> list[ValidationError]:
    # The SDK stores url() as {"field": <name>, "value": <url>}.
    field_name = args.get("field") or args.get("name")
    if not isinstance(field_name, str) or not field_name:
        return [ValidationError(
            kind="missing_url_field", verb="url", name=str(field_name),
            message="url() requires a slot name (e.g. 'DiscordUrl')",
        )]
    if field_name in KNOWN_URL_FIELDS:
        return []
    return [ValidationError(
        kind="unknown_url_field", verb="url", name=field_name,
        message=f"unknown URL slot {field_name!r}",
        suggestion=_suggest(field_name, KNOWN_URL_FIELDS),
    )]


# --- public API -----------------------------------------------------------


def validate_mod(
    mod_state,
    *,
    asset_map_path: Optional[Path] = None,
) -> list[ValidationError]:
    """Run every static check the SDK can perform without touching the
    live game install. Returns the (possibly empty) list of errors.

    `mod_state` is duck-typed: anything with `.patches` whose items have
    `.kind` and `.args` works (an `sdk.Mod` instance is the canonical
    case; tests pass simple namespaces).
    """
    cat = _build_catalog(asset_map_path)
    errors: list[ValidationError] = []

    for patch in getattr(mod_state, "patches", []):
        kind = getattr(patch, "kind", None)
        args = getattr(patch, "args", None) or {}
        if kind == "stat":
            errors.extend(_check_stat(args, cat))
        elif kind == "texture":
            errors.extend(_check_texture(args, cat))
        elif kind == "text":
            errors.extend(_check_text(args, cat))
        elif kind == "url":
            errors.extend(_check_url(args))
        # `raw` and `composite` patches are intentionally not statically
        # validated — raw bytes can land anywhere, composite recipes are
        # placeholders whose backing schemas don't exist yet.

    return errors


def format_errors(errors: list[ValidationError]) -> str:
    """Render a list of ValidationError into a multi-line message
    suitable for `raise SystemExit(format_errors(errs))`. Empty input
    yields an empty string."""
    if not errors:
        return ""
    lines = [f"{len(errors)} validation error(s):"]
    for e in errors:
        head = f"  [{e.verb}] {e.message}"
        if e.suggestion and e.suggestion != e.name:
            head += f"  -- did you mean {e.suggestion!r}?"
        lines.append(head)
    return "\n".join(lines)


__all__ = [
    "ValidationError",
    "validate_mod",
    "format_errors",
    "KNOWN_URL_FIELDS",
    "KNOWN_TEXT_LANGS",
]
