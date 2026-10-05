"""Whether a mod is client-only, decided from what it contains.

A client-only mod changes what one player sees or reads, never the game the
party plays: a damage meter, a HUD overlay, a camera change, a texture or sound
swap, new UI text. Those are the mods that can sensibly be allowed in public
matchmaking. Everything else is a *gameplay* mod.

The manifest's ``multiplayer_scope`` cannot answer this. It is the author's own
claim, and when this module was written a dozen mods in the repo that set HP,
grant items or edit talents declared ``local-only`` — and a missing value
defaulted to ``cosmetic``. So the verdict here is DERIVED, and it fails closed:
anything not positively known to be client-only is gameplay, and every reason
is reported so an author can see what to change.

What counts as client-only:

* no ``[[content]]`` and no ``[[patch]]`` in the manifest (both edit game data);
* asset overrides only in presentation families: cooked textures, FMOD sound
  banks, UI text banks, and the mod's own ``lang/`` strings;
* Lua that touches the SDK only through :data:`CLIENT_NAMESPACES` (whole
  namespaces) and :data:`CLIENT_CALLS` (single functions). Any other ``R.*``
  path, dynamic access (``R[...]``), passing the SDK table around, the native
  ``rsmm.*`` bindings, or requiring an SDK internal (``rsmm.*``) is gameplay.

Camera changes are client-only by decision (2026-10-05): the camera is local
and nothing about it reaches another player. Map reveal is not — it is a
``[[patch]]`` mod and edits game data like any other.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: SDK namespaces whose every member is client-only: logging, timers, the mod's
#: own config / storage / experiments, the HUD overlay, the read-only damage
#: meter, the boot canary, local translation lookup, and the camera.
CLIENT_NAMESPACES: frozenset[str] = frozenset({
    "log", "on", "off", "once", "on_match",
    "overlay", "exp", "kv", "config", "schedule", "health", "i18n",
    "damage", "camera",
})

#: Single client-only functions inside otherwise-gameplay namespaces: reads.
CLIENT_CALLS: frozenset[str] = frozenset({
    "entity.hero", "entity.ready", "entity.capture_enabled",
    "entity.hp", "entity.hp_frac", "entity.max_hp",
    "stat.get", "stat.cached", "stat.keys", "stat.names", "stat.key",
    "hp.get", "hp.frac", "hp.max",
    "events.known", "events.count", "events.category",
})


_IDENT = r"[A-Za-z_]\w*"
_REQUIRE_RE = re.compile(
    rf"(?:local\s+)?({_IDENT})\s*=\s*require\s*\(?\s*(['\"])([\w.]+)\2\s*\)?")
_ANY_REQUIRE_RE = re.compile(r"require\s*\(?\s*(['\"])([\w.]+)\1")


@dataclass
class ScopeVerdict:
    """The derived verdict for one mod. ``reasons`` is empty iff client-only."""

    mod: str
    reasons: list[str] = field(default_factory=list)

    @property
    def client_only(self) -> bool:
        return not self.reasons


def asset_is_client_only(decoded: str) -> bool:
    """Whether overriding this decoded asset path changes only presentation."""
    p = decoded.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    if name.endswith((".Texture.dxt", ".Texture.nrm")):
        return True
    if p.startswith("Audio/") and name.endswith(".bank"):
        return True
    return p.startswith("Text/") and name.endswith(".LocalText.gen")


# ---- Lua --------------------------------------------------------------------

def _strip_comments(src: str) -> str:
    """Remove Lua comments, keeping string literals (requires live in them)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src.startswith("--", i):
            m = re.match(r"--\[(=*)\[", src[i:])
            if m:
                end = src.find("]" + m.group(1) + "]", i + m.end())
                i = n if end < 0 else end + len(m.group(1)) + 2
            else:
                nl = src.find("\n", i)
                i = n if nl < 0 else nl
        elif c == "[" and re.match(r"\[(=*)\[", src[i:]):
            m = re.match(r"\[(=*)\[", src[i:])
            end = src.find("]" + m.group(1) + "]", i + m.end())
            stop = n if end < 0 else end + len(m.group(1)) + 2
            out.append(src[i:stop])
            i = stop
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _blank_strings(src: str) -> str:
    """Replace string literals with an empty string, so text is not code."""
    src = re.sub(r"\[(=*)\[.*?\]\1\]", '""', src, flags=re.S)
    return re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", '""', src)


def lua_reasons(src: str) -> list[str]:
    """Why this Lua source is gameplay; empty when it is client-only."""
    code = _strip_comments(src)
    reasons: list[str] = []
    aliases = {"R"}
    for m in _REQUIRE_RE.finditer(code):
        if m.group(3) == "rsmm":
            aliases.add(m.group(1))
    for m in _ANY_REQUIRE_RE.finditer(code):
        if m.group(2).startswith("rsmm."):
            reasons.append(f"requires the SDK internal \"{m.group(2)}\"")

    code = _blank_strings(code)
    if "rsmm" not in aliases and re.search(r"(?<![\w.])rsmm\s*[.\[:]", code):
        reasons.append("uses the native loader bindings (rsmm.*)")

    for alias in sorted(aliases):
        ref = re.compile(rf"(?<![\w.]){re.escape(alias)}\b((?:\s*\.\s*{_IDENT})*)(\s*[\[:]?)")
        for m in ref.finditer(code):
            chain = [p.strip() for p in m.group(1).split(".") if p.strip()]
            if m.group(2).strip() in ("[", ":"):
                reasons.append(f"accesses the SDK dynamically ({alias}{m.group(2).strip()}...)")
                continue
            if not chain:
                before = code[max(0, m.start() - 40):m.start()]
                after = code[m.end():m.end() + 30]
                if re.search(rf"local\s+{re.escape(alias)}\s*$", before) or \
                        re.match(r"\s*=\s*require\b", after):
                    continue  # the alias's own declaration
                reasons.append(f"passes the SDK table ({alias}) around, "
                               "so its use cannot be checked")
                continue
            if chain[0] in CLIENT_NAMESPACES:
                continue
            if len(chain) >= 2 and f"{chain[0]}.{chain[1]}" in CLIENT_CALLS:
                continue
            reasons.append(f"calls {alias}.{'.'.join(chain[:2])}")
    return sorted(set(reasons))


# ---- whole mods ---------------------------------------------------------------

def manifest_reasons(manifest: dict) -> list[str]:
    reasons = []
    if manifest.get("content"):
        n = len(manifest["content"])
        reasons.append(f"adds or changes game content ({n} [[content]] entries)")
    if manifest.get("patch"):
        reasons.append(f"patches game data ({len(manifest['patch'])} [[patch]] entries)")
    return reasons


def _load_manifest(mod_dir: Path) -> tuple[dict, list[str]]:
    try:
        return tomllib.loads((mod_dir / "manifest.toml").read_text(encoding="utf-8")), []
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError) as e:
        return {}, [f"manifest.toml cannot be read ({e})"]


def classify_mod_dir(mod_dir: Path) -> ScopeVerdict:
    """Classify a mod's source folder (what `rsmm lint` sees)."""
    mod_dir = Path(mod_dir)
    manifest, reasons = _load_manifest(mod_dir)
    verdict = ScopeVerdict(str(manifest.get("mod", {}).get("id") or mod_dir.name))
    verdict.reasons += reasons + manifest_reasons(manifest)

    for lua in sorted(mod_dir.rglob("*.lua")):
        try:
            text = lua.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            verdict.reasons.append(f"{lua.name} cannot be read ({e})")
            continue
        rel = lua.relative_to(mod_dir).as_posix()
        verdict.reasons += [f"{rel}: {r}" for r in lua_reasons(text)]

    assets = mod_dir / "assets"
    if assets.is_dir():
        for f in sorted(p for p in assets.rglob("*") if p.is_file()):
            rel = f.relative_to(assets).as_posix()
            if rel.startswith("_root/"):
                verdict.reasons.append(f"replaces a game-root file ({rel[6:]})")
            elif not asset_is_client_only(rel):
                verdict.reasons.append(f"overrides game data ({rel})")
    # `lang/` (the mod's own UI strings) is presentation; `_root/` replaces
    # files in the game folder itself, which is never presentation-only.
    if (mod_dir / "_root").is_dir():
        verdict.reasons.append("replaces game-root files (_root/)")
    verdict.reasons = sorted(set(verdict.reasons))
    return verdict


def classify_runtime(game_mod_dir: Path, decoded_assets: list[str]) -> ScopeVerdict:
    """Classify a mod as it is APPLIED to a game: its runtime folder under
    ``<game>/mods/`` (manifest + Lua the loader runs) and the decoded paths of
    the asset overrides the apply journal records for it."""
    game_mod_dir = Path(game_mod_dir)
    manifest, reasons = _load_manifest(game_mod_dir)
    verdict = ScopeVerdict(str(manifest.get("mod", {}).get("id") or game_mod_dir.name))
    verdict.reasons += reasons + manifest_reasons(manifest)
    if game_mod_dir.is_dir():
        for lua in sorted(game_mod_dir.glob("*.lua")):
            try:
                text = lua.read_text(encoding="utf-8", errors="replace")
            except OSError:
                verdict.reasons.append(f"{lua.name} cannot be read")
                continue
            verdict.reasons += [f"{lua.name}: {r}" for r in lua_reasons(text)]
    for dec in decoded_assets:
        if not asset_is_client_only(dec):
            verdict.reasons.append(f"overrides game data ({dec})")
    verdict.reasons = sorted(set(verdict.reasons))
    return verdict
