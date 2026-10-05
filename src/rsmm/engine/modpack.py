"""Identity of an install's applied mod set, for multiplayer matching.

Ravenswatch is host-authoritative P2P over a shared asset set, so two players
whose installs have different asset bytes can desync. The backend matches
parties on the fingerprint computed here (see
``services/stormancer/README.md``), which travels inside the signed login
ticket.

Not to be confused with ``rsmm pack``, which bundles ONE mod for distribution.
This is the fingerprint of *everything* currently applied to an install.

Only GAMEPLAY mods count (``rsmm.engine.mod_scope``). A client-only mod — a
damage meter, a texture swap, a camera change — cannot desync anyone, so an
install running only those is ``client-only``: no fingerprint, matched like a
vanilla install, and the status public matchmaking can allow. Lua mods count
too, from the runtime copies the loader actually runs in ``<game>/mods/``: they
never touch the apply journal, so until 2026-10-05 an install running
``lucky-chests`` or ``sprint`` reported itself as vanilla.

Derived from applied bytes, not from mod ids and versions, on purpose. Two
installs can agree on every ``id@version`` and still hold different bytes — a
different SDK version cooked the asset, or the author edited it in place — and
those installs desync. Hashing what was actually written catches that; hashing
the version list does not. It also means a renamed mod with identical content
still matches, which is the behaviour we want.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rsmm.engine.paths import COOKING_SUBDIR

#: Hex characters kept from the digest. Short enough to read in a log line,
#: long enough that an accidental collision between two real mod sets is not a
#: practical concern (64 bits).
ID_LENGTH = 16

#: Name of the apply journal, relative to the cooking dir. Duplicated from
#: `rsmm.cli.apply_mods` rather than imported: `engine` must not depend on
#: `cli`, and a one-line constant is cheaper than the inversion.
STATE_FILE_NAME = ".rsmm_state.json"

#: How many mod ids a label names before it summarises the rest.
_LABEL_NAMES = 3


def modpack_id(active: Mapping[str, Mapping],
               lua: Mapping[str, str] | None = None) -> str | None:
    """Fingerprint of the applied override set, or None when it is unknowable.

    `active` is the apply journal's ``active`` map: encoded path -> entry.

    Returns None — meaning "unknown", which the backend treats as "do not
    refuse" — in two cases:

    * nothing is applied, i.e. a vanilla install;
    * any entry has no usable ``src_sha256``. Pre-0.1.12 journals recorded
      ``src_sha1`` instead and those keys are ignored on read, so the set
      cannot be hashed faithfully. Returning a fingerprint computed from a
      partial set would be worse than admitting ignorance: it would claim two
      installs match when nothing checked the rest. The next ``rsmm apply``
      rewrites the journal and the id becomes available.

    The encoded path is used as the key because it is derived from the decoded
    path by a fixed cipher, so it is identical on every machine.

    `lua` maps a running Lua mod's folder name to the digest of its runtime
    files (:func:`runtime_digest`); those join the set under a ``lua:`` prefix,
    which no encoded path can start with.
    """
    if not active and not lua:
        return None

    lines = []
    for encoded, entry in active.items():
        digest = entry.get("src_sha256") if isinstance(entry, Mapping) else None
        if not isinstance(digest, str) or not digest:
            return None
        # NUL separates the two fields so no path or digest can forge a
        # boundary, and the trailing newline keeps entries from running
        # together.
        lines.append(f"{encoded}\0{digest}\n")
    for name, digest in (lua or {}).items():
        lines.append(f"lua:{name}\0{digest}\n")

    # Sorted, because a dict's order reflects the order `apply` happened to
    # walk the mods — which differs between machines that applied the same set.
    joined = "".join(sorted(lines))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:ID_LENGTH]


def applied_mod_ids(active: Mapping[str, Mapping]) -> list[str]:
    """The distinct mod ids that own the applied overrides, sorted.

    Taken from the journal's ``active`` map rather than its ``enabled_mods``
    list, because those answer different questions. ``enabled_mods`` is what the
    manifests ask for; ``active`` is what is on disk. They diverge routinely —
    after ``restore --all`` every mod is still enabled and nothing is applied —
    and only what is on disk can desync a party, so the label has to describe
    the same set the fingerprint does.
    """
    ids = set()
    for entry in active.values():
        if isinstance(entry, Mapping):
            mod = entry.get("mod")
            if isinstance(mod, str) and mod:
                ids.add(mod)
    return sorted(ids)


def modpack_label(mod_ids: Sequence[str]) -> str | None:
    """A human-readable name for the set, for log lines and the CLI only.

    Never used for matching — only `modpack_id` decides that — so it is free to
    be lossy.
    """
    # A bare string is a Sequence of characters, so an unguarded call would
    # render "abc" as "a, b, c". Treat one name as one name.
    if isinstance(mod_ids, str):
        mod_ids = [mod_ids]
    names = sorted({m for m in mod_ids if m and isinstance(m, str)})
    if not names:
        return None
    if len(names) <= _LABEL_NAMES:
        return ", ".join(names)
    rest = len(names) - _LABEL_NAMES
    return f"{', '.join(names[:_LABEL_NAMES])} +{rest} more"


def runtime_digest(mod_dir: Path) -> str | None:
    """Digest of a runtime mod folder's files (what the loader reads), or None
    when one cannot be read."""
    h = hashlib.sha256()
    try:
        for f in sorted(p for p in Path(mod_dir).iterdir() if p.is_file()):
            h.update(f"{f.name}\0{hashlib.sha256(f.read_bytes()).hexdigest()}\n".encode())
    except OSError:
        return None
    return h.hexdigest()


def running_lua_mods(game_dir: Path) -> list[Path]:
    """Runtime folders under ``<game>/mods/`` whose Lua the loader will run.

    `apply` removes a disabled mod's ``init.lua`` but keeps its manifest, so the
    presence of Lua is what "running" means; the loader's own files live at the
    top level and are not folders.
    """
    root = Path(game_dir) / "mods"
    try:
        return sorted(d for d in root.iterdir()
                      if d.is_dir() and not d.name.startswith(("_", "."))
                      and any(d.glob("*.lua")))
    except OSError:
        return []


@dataclass(frozen=True)
class Modpack:
    """What an install is running, and whether we could tell.

    `status` is separate from `id` because a null id has two meanings that must
    not be shown to a player as one. Both travel to the backend as no pack and
    are failed open on, but only one of them is worth acting on:

    * ``vanilla`` — nothing applied. Correct and final.
    * ``client-only`` — only client-only mods run. No fingerprint: these match
      a vanilla install, and are what public matchmaking can allow.
    * ``ok`` — gameplay mods run, and a fingerprint was computed.
    * ``unknown`` — something is applied but could not be fingerprinted (a
      pre-0.1.12 journal, or one that is missing/corrupt). ``rsmm apply``
      rewrites it.
    """

    id: str | None
    label: str | None
    status: str
    #: Running mods that change the game, each with the reasons it does.
    gameplay: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: Running mods that are client-only.
    client_only: tuple[str, ...] = ()

    @property
    def matchable(self) -> bool:
        """Whether this install can be matched against another at all."""
        return self.status in ("ok", "vanilla", "client-only")

    @property
    def public_matchmaking_ok(self) -> bool:
        """No gameplay mod is running, so the game is the vanilla game."""
        return self.status in ("vanilla", "client-only")


def read_modpack(game_dir: Path) -> Modpack:
    """What an install is running, read from its apply journal.

    A missing or corrupt journal is not an error worth raising: the caller is
    about to launch a game, and `rsmm doctor` is what diagnoses the journal.
    """
    state_path = Path(game_dir) / COOKING_SUBDIR / STATE_FILE_NAME
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # The manager never touched this install, which is a vanilla game.
        return Modpack(None, None, "vanilla")
    except (OSError, ValueError):
        return Modpack(None, None, "unknown")
    if not isinstance(raw, dict):
        return Modpack(None, None, "unknown")

    # Defended rather than trusted: the journal is a file on a player's disk,
    # and this runs on the launch path where raising is worse than reporting
    # "unknown".
    active = raw.get("active")
    if not isinstance(active, Mapping):
        active = {}

    from rsmm.engine.cipher import decode
    from rsmm.engine.mod_scope import classify_runtime

    # Which mod each applied file belongs to, by decoded path.
    by_mod: dict[str, list[str]] = {}
    for encoded, entry in active.items():
        mod = entry.get("mod") if isinstance(entry, Mapping) else None
        by_mod.setdefault(mod if isinstance(mod, str) and mod else "?",
                          []).append(encoded)
    lua_dirs = {d.name: d for d in running_lua_mods(game_dir)}

    gameplay: list[tuple[str, tuple[str, ...]]] = []
    client_only: list[str] = []
    gameplay_active: dict[str, Mapping] = {}
    lua_digests: dict[str, str] = {}
    unreadable = False
    for name in sorted(set(by_mod) | set(lua_dirs)):
        encoded_paths = by_mod.get(name, [])
        decoded = [decode(e.replace("\\", "/")) for e in encoded_paths]
        verdict = classify_runtime(Path(game_dir) / "mods" / name, decoded)
        if verdict.client_only:
            client_only.append(name)
            continue
        gameplay.append((name, tuple(verdict.reasons)))
        for e in encoded_paths:
            gameplay_active[e] = active[e]
        if name in lua_dirs:
            digest = runtime_digest(lua_dirs[name])
            if digest is None:
                unreadable = True
            else:
                lua_digests[name] = digest

    label = modpack_label([*(g for g, _ in gameplay), *client_only])
    common = {"gameplay": tuple(gameplay), "client_only": tuple(client_only)}
    if not gameplay:
        status = "client-only" if client_only else "vanilla"
        return Modpack(None, label, status, **common)
    pack_id = None if unreadable else modpack_id(gameplay_active, lua_digests)
    if pack_id is not None:
        return Modpack(pack_id, label, "ok", **common)
    # Gameplay mods run but could not be hashed (an old journal, an unreadable
    # runtime folder): say so rather than claim a fingerprint for part of them.
    return Modpack(None, label, "unknown", **common)
