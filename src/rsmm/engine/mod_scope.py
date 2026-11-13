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
  So is any way of obtaining the SDK that the scan cannot follow by name: a
  ``require`` whose argument is not one plain string, the SDK bound anywhere
  but ``local NAME = require "rsmm"``, and ``_G`` / ``_ENV`` / ``package``.

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
#: meter, the boot canary, local translation lookup, the camera, the
#: master audio mute (FMOD mixes on each machine; nothing is sent), and local
#: mouse-wheel input plus a read of the player's own key bindings.
CLIENT_NAMESPACES: frozenset[str] = frozenset({
    "log", "on", "off", "once", "on_match",
    "overlay", "exp", "kv", "config", "schedule", "health", "i18n",
    "damage", "camera", "audio", "input",
})

#: Single client-only functions inside otherwise-gameplay namespaces: reads.
CLIENT_CALLS: frozenset[str] = frozenset({
    "entity.hero", "entity.ready", "entity.capture_enabled",
    "entity.hp", "entity.hp_frac", "entity.max_hp",
    "stat.get", "stat.cached", "stat.keys", "stat.names", "stat.key",
    "hp.get", "hp.frac", "hp.max",
    "events.known", "events.count", "events.category",
    # Reads the netcode peer table (names, session ids) — no write, no send.
    "net.peers",
    # Read the lobby roster the loader already parsed — names and hero picks.
    "lobby.members", "lobby.allies", "lobby.hero_name",
    # Logs the hero's live component list; reads only (R.debug.observe hooks,
    # so the namespace as a whole is not client-only).
    "debug.components",
    # Reads of the global entity-value context ("Is menu open", "Current
    # chapter"); R.game has no public setter.
    "game.get", "game.flag", "game.cached", "game.ready", "game.describe",
})


_IDENT = r"[A-Za-z_]\w*"

#: A module name `require` can be checked against: plain characters only, so
#: an escape (`"\114smm"`) is not read as some other name.
_MODULE_NAME_RE = re.compile(r"[\w.\-]+")
#: Globals that reach the SDK without naming it: the global table, the
#: environment, and the module cache that holds every loaded module. Only
#: GLOBAL reads count: a field (`label.package`), a table key
#: (`{ package = "HUD" }`) or a local of the same name is not these.
_ENV_GLOBALS: dict[str, str] = {
    "_G": "the global table (_G)",
    "_ENV": "the environment table (_ENV)",
    "package": "the module cache (package)",
}
#: Keywords a statement can directly follow (they end one, or open a block).
_BEFORE_STATEMENT_KW = frozenset({
    "do", "then", "else", "repeat", "end", "break", "true", "false", "nil",
})


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


def _can_start_statement(toks: list, k: int) -> bool:
    """Whether a statement can begin at token `k`: the token before it ends a
    statement (or opens a block) rather than continuing an expression or a
    target list (`t.S`, `a, S`)."""
    if k == 0:
        return True
    prev = toks[k - 1]
    if prev.kind == "op":
        return prev.text in (";", ")", "]", "}")
    if prev.kind == "kw":
        return prev.text in _BEFORE_STATEMENT_KW
    return True  # a name, string or number ends the previous statement


def _ends_statement(toks: list, k: int) -> bool:
    """Whether the expression before token `k` is complete there, so nothing
    (`.stat`, `or {}`, a call) carries the value further. Lua ignores line
    breaks, so this looks at the next token, not the next line."""
    if k >= len(toks):
        return True
    tok = toks[k]
    if tok.kind == "op":
        return tok.text == ";"
    if tok.kind == "kw":
        return tok.text not in ("and", "or")
    return tok.kind == "name"


def _sdk_access_reasons(src: str, aliases: set[str]) -> list[str]:
    """Check how `src` reaches the SDK; add each binding that can be followed
    to `aliases`, and return a reason for every other way in.

    The scan in :func:`lua_reasons` follows the SDK by NAME, so it only works
    while every way of obtaining the SDK is one it recognizes. Each check here
    closes a way of getting the SDK under a name the scan never learns, which
    would otherwise let a mod calling gameplay functions be classified
    client-only. It works on Lua tokens and the walk's scopes, not on lines:
    Lua ignores line breaks, and a field, table key or local named like a
    global is not that global.
    """
    from rsmm.cli._lua_scope import LuaSyntaxError, walk

    try:
        w = walk(src)
    except LuaSyntaxError as e:
        return [f"its Lua cannot be parsed ({e}), so its use of the SDK "
                "cannot be checked"]
    toks = w.t
    reasons: list[str] = []
    unfollowed = ("stores the SDK somewhere other than a plain local "
                  "(`local R = require \"rsmm\"`), so its use cannot be checked")
    globals_read = {name for name, _ in w.globals}

    for name, k in w.globals:
        if name != "require":
            continue
        nxt = toks[k + 1] if k + 1 < len(toks) else None
        if nxt is not None and nxt.kind == "str":
            arg, end = nxt.text, k + 2
        elif (nxt is not None and nxt.kind == "op" and nxt.text == "("
              and k + 3 < len(toks) and toks[k + 2].kind == "str"
              and toks[k + 3].kind == "op" and toks[k + 3].text == ")"):
            arg, end = toks[k + 2].text, k + 4
        else:
            reasons.append("uses require with something other than a plain "
                           "string, so what it loads cannot be checked")
            continue
        if not _MODULE_NAME_RE.fullmatch(arg):
            reasons.append("uses require with something other than a plain "
                           "string, so what it loads cannot be checked")
            continue
        if arg.startswith("rsmm."):
            reasons.append(f"requires the SDK internal \"{arg}\"")
            continue
        if arg != "rsmm":
            continue
        if k in w.nested or not _ends_statement(toks, end):
            reasons.append(unfollowed)
            continue
        if _can_start_statement(toks, k):
            continue  # a bare `require "rsmm"` statement binds nothing
        # `[local] NAME = require "rsmm"`, the one binding that can be followed.
        eq, target = toks[k - 1], toks[k - 2] if k >= 2 else None
        if not (eq.kind == "op" and eq.text == "=" and target is not None
                and target.kind == "name"):
            reasons.append(unfollowed)
            continue
        declared = k >= 3 and toks[k - 3].kind == "kw" and toks[k - 3].text == "local"
        if not declared and not _can_start_statement(toks, k - 2):
            reasons.append(unfollowed)
            continue
        if target.text == "_ENV":
            # Every free name in the file would then be an SDK field.
            reasons.append("makes the SDK its environment (_ENV), so its use "
                           "cannot be checked")
            continue
        aliases.add(target.text)

    for name, what in _ENV_GLOBALS.items():
        if name in globals_read:
            reasons.append(f"reaches {what}, which holds the SDK under a "
                           "name that cannot be checked")
    if "rsmm" in globals_read and "rsmm" not in aliases:
        reasons.append("uses the native loader bindings (rsmm.*)")
    return reasons


def lua_reasons(src: str) -> list[str]:
    """Why this Lua source is gameplay; empty when it is client-only."""
    aliases = {"R"}
    reasons = _sdk_access_reasons(src, aliases)
    code = _blank_strings(_strip_comments(src))

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


# ---- the "Private games only" label -------------------------------------------

#: The registry's label for a mod that changes the game the party plays
#: (packages/schemas/src/private-only.ts). The site shows it, keeps the mod out
#: of public lobbies' expectations, and only an admin can remove it.
PRIVATE_ONLY_TAG = "private-only"
#: Spellings the registry reads as the same label (keep in step with
#: PRIVATE_ONLY_TAG_ALIASES in packages/schemas/src/private-only.ts).
PRIVATE_ONLY_TAG_ALIASES = frozenset({
    "private-only", "private only", "private-games-only", "private games only",
    "cheat", "cheats",
})

_MOD_HEADER_RE = re.compile(r"^\[mod\][^\S\r\n]*(?:#[^\r\n]*)?\r?\n?", re.MULTILINE)
_NEXT_TABLE_RE = re.compile(r"^\[", re.MULTILINE)
_TAGS_RE = re.compile(r"^(?P<lhs>tags[^\S\r\n]*=[^\S\r\n]*)\[", re.MULTILINE)


def has_private_only_tag(tags) -> bool:
    return any(isinstance(t, str) and t.strip().lower() in PRIVATE_ONLY_TAG_ALIASES
               for t in tags or ())


def private_only_tags(tags, verdict: ScopeVerdict) -> list[str]:
    """``tags`` with the "Private games only" label added when ``verdict`` says
    the mod changes the game. The engine decides, not the author: a gameplay
    mod is labelled whatever its manifest says, and a client-only mod keeps an
    author's own label (it is theirs to ask for)."""
    out = [str(t) for t in tags or () if isinstance(t, str)]
    if not verdict.client_only and not has_private_only_tag(out):
        out.append(PRIVATE_ONLY_TAG)
    return out


def stamp_private_only(text: str) -> str | None:
    """``text`` (a manifest.toml) with the label added to ``[mod].tags``, or
    None when it already has it or cannot be stamped safely. Only the
    ``[mod]`` table is touched, the rest of the file keeps its bytes, and the
    result must parse to the same manifest plus the label (else None)."""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    mod = before.get("mod")
    if not isinstance(mod, dict) or has_private_only_tag(mod.get("tags")):
        return None
    head = _MOD_HEADER_RE.search(text)
    if head is None:
        return None
    rest = text[head.end():]
    nxt = _NEXT_TABLE_RE.search(rest)
    body = rest[:nxt.start()] if nxt else rest
    tags = _TAGS_RE.search(body)
    if tags is None:
        nl = "\r\n" if "\r\n" in text else "\n"
        body = f'tags = ["{PRIVATE_ONLY_TAG}"]{nl}' + body
    else:
        close = body.find("]", tags.end())
        if close < 0:
            return None
        inner = body[tags.end():close]
        sep = "" if not inner.strip() else ("" if inner.rstrip().endswith(",") else ",")
        lead = "" if not inner.strip() else " "
        body = (body[:close].rstrip(" \t") + f'{sep}{lead}"{PRIVATE_ONLY_TAG}"'
                + (" " if inner.endswith(" ") and inner.strip() else "") + body[close:])
    out = text[:head.end()] + body + (rest[nxt.start():] if nxt else "")
    try:
        after = tomllib.loads(out)
    except tomllib.TOMLDecodeError:
        return None
    want = dict(before)
    want["mod"] = {**mod, "tags": [*(mod.get("tags") or []), PRIVATE_ONLY_TAG]}
    return out if after == want else None
