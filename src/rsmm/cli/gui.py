"""
rsmm gui — local web UI mod manager.

Localhost HTTP server (stdlib only). Modern multi-page mod manager:

  - Mods      list installed mods, toggle each, view detail / delete
  - Install   drag-drop a .zip into mods/ (validates manifest.toml)
  - Tools     apply / restore / build / install-loader / run
  - Settings  game-dir / platform / decoder status

Side-nav icons come live from the game install
(<game>/DarkTalesResources/_Cooking/<encoded>) via the optional
texture2ddecoder + Pillow stack — falls back to text labels if those
libs aren't available.

Cross-platform (Win / Linux / macOS). Browser auto-opens via
`webbrowser`. Server binds to 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import hmac
import io
import json
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Per-process auth + CSRF tokens. Generated fresh at server start in
# main(); printed once to stderr; embedded in the auto-opened browser
# URL. All /api/* requests must present AUTH_TOKEN (cookie or `?t=`);
# POSTs must additionally present CSRF_TOKEN in X-RSMM-CSRF header.
AUTH_TOKEN: str = ""
CSRF_TOKEN: str = ""
BOUND_HOST: str = ""   # "127.0.0.1:<port>"

from rsmm.engine.paths import (
    REPO_ROOT, MODS_DIR, DEFAULT_GAME_DIR, COOKING_SUBDIR, ASSET_MAP_JSON,
)


# ──────────────────────────────────────────────────────────────────────
# manifest toggle / load
# ──────────────────────────────────────────────────────────────────────

ENABLED_LINE = re.compile(
    r"^(?P<indent>\s*)enabled(?P<spaces>\s*=\s*)(?P<val>true|false)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _toggle_mod(mod_id: str, enabled: bool) -> tuple[bool, str]:
    mod_dir = MODS_DIR / mod_id
    mf = mod_dir / "manifest.toml"
    if not mf.is_file():
        return False, f"no such mod: {mod_id}"
    text = mf.read_text(encoding="utf-8")
    new_val = "true" if enabled else "false"
    if ENABLED_LINE.search(text):
        text = ENABLED_LINE.sub(
            lambda m: f"{m.group('indent')}enabled{m.group('spaces')}{new_val}",
            text, count=1,
        )
    elif re.search(r"(?m)^\[mod\]\s*$", text):
        text = re.sub(r"(?m)^\[mod\]\s*$",
                      f"[mod]\nenabled = {new_val}",
                      text, count=1)
    else:
        text = f"[mod]\nenabled = {new_val}\n" + text
    mf.write_text(text, encoding="utf-8")
    return True, f"set {mod_id}.enabled = {new_val}"


def _load_mods() -> list[dict]:
    from rsmm.cli.merge import _toml_load
    out: list[dict] = []
    if not MODS_DIR.is_dir():
        return out
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        mf = entry / "manifest.toml"
        if not mf.is_file():
            continue
        try:
            t = _toml_load(mf)
        except Exception as e:
            out.append({"id": entry.name, "error": str(e)})
            continue
        meta = t.get("mod", {})
        n_assets = 0
        adir = entry / "assets"
        if adir.is_dir():
            # _pending_* dirs are SDK content-emission staging; exclude
            # them from the asset count so the card reflects what the
            # user actually shipped.
            n_assets = sum(
                1 for p in adir.rglob("*")
                if p.is_file() and not any(
                    seg.startswith("_pending_") for seg in p.relative_to(adir).parts
                )
            )
        n_root = 0
        rdir = entry / "_root"
        if rdir.is_dir():
            n_root = sum(1 for p in rdir.rglob("*") if p.is_file())
        n_patches = len(t.get("patch", []) or [])
        has_lua = (entry / "init.lua").is_file()
        content_blocks = list(t.get("content", []) or [])

        # SDK v3 per-mod surfaces. Best-effort — never raise out of the
        # mod-list endpoint just because one mod's config_schema is bad.
        config_schema: dict[str, dict] = {}
        config_values: dict[str, object] = {}
        config_error: str | None = None
        try:
            from rsmm.sdk.config import ConfigStore, ConfigError as _CE
            try:
                store = ConfigStore(entry)
                for name, f in store.schema.fields.items():
                    config_schema[name] = {
                        "type":    f.type,
                        "default": f.default,
                        "min":     f.min,
                        "max":     f.max,
                        "choices": list(f.choices),
                        "label":   f.label,
                    }
                config_values = store.all()
            except _CE as e:
                config_error = str(e)
        except Exception:
            pass

        locales: list[str] = []
        try:
            from rsmm.sdk.i18n import I18nBundle
            bundle = I18nBundle.load(meta.get("id") or entry.name, entry)
            locales = sorted(bundle.by_locale.keys())
        except Exception:
            pass

        out.append({
            "id":             meta.get("id") or entry.name,
            "folder":         entry.name,
            "name":           meta.get("name") or entry.name,
            "version":        meta.get("version", ""),
            "author":         meta.get("author", ""),
            "description":    meta.get("description", ""),
            "enabled":        bool(meta.get("enabled", True)),
            "load_order":     int(meta.get("load_order", 100)),
            "sdk_version":    str(meta.get("sdk_version", "")),
            "files_assets":   n_assets,
            "files_root":     n_root,
            "patches":        n_patches,
            "has_lua":        has_lua,
            "content":        content_blocks,
            "config_schema":  config_schema,
            "config_values":  config_values,
            "config_error":   config_error,
            "locales":        locales,
        })
    return out


# ──────────────────────────────────────────────────────────────────────
# manifest field editor
# ──────────────────────────────────────────────────────────────────────

# Editable scalar fields on `[mod]`. We don't touch unknown / nested
# tables; users wanting that can edit manifest.toml by hand.
EDITABLE_FIELDS = {
    "name":        "str",
    "version":     "str",
    "author":      "str",
    "description": "str",
    "enabled":     "bool",
    "load_order":  "int",
    "sdk_version": "str",
}


def _toml_quote(s: str) -> str:
    """Encode `s` as a TOML basic string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _format_value(kind: str, value) -> str:
    if kind == "bool":
        return "true" if value else "false"
    if kind == "int":
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return "0"
    if kind == "float":
        try:
            return f"{float(value):g}"
        except (TypeError, ValueError):
            return "0"
    return _toml_quote("" if value is None else str(value))


def _set_field(text: str, key: str, raw_rhs: str) -> str:
    """Set `key = <raw_rhs>` inside the [mod] table of a TOML doc,
    preserving every other byte. Inject under [mod] if missing; create
    the [mod] table if absent."""
    mod_hdr = re.search(r"(?m)^\[mod\]\s*$", text)
    if not mod_hdr:
        return f"[mod]\n{key} = {raw_rhs}\n\n" + text
    start = mod_hdr.end()
    next_hdr = re.search(r"(?m)^\[", text[start:])
    end = start + next_hdr.start() if next_hdr else len(text)
    section = text[start:end]

    pat = re.compile(
        rf"^(?P<lead>[ \t]*){re.escape(key)}(?P<sp>[ \t]*=[ \t]*).*$",
        re.MULTILINE,
    )
    new_section, n = pat.subn(
        lambda m: f"{m.group('lead')}{key}{m.group('sp')}{raw_rhs}",
        section, count=1,
    )
    if n == 0:
        # Insert right after the [mod] header so updates cluster
        # together. Preserve any blank line that already follows.
        new_section = "\n" + f"{key} = {raw_rhs}" + new_section
    return text[:start] + new_section + text[end:]


def _update_mod(mod_id: str, fields: dict) -> dict:
    """Rewrite scalar fields in mods/<id>/manifest.toml. Returns
    {ok, msg}. Unknown fields are silently dropped (front-end shouldn't
    send them anyway)."""
    if not mod_id or not ID_RE.match(mod_id):
        return {"ok": False, "msg": f"bad mod id: {mod_id!r}"}
    mf = MODS_DIR / mod_id / "manifest.toml"
    if not mf.is_file():
        return {"ok": False, "msg": f"no manifest for {mod_id}"}
    text = mf.read_text(encoding="utf-8")

    applied = []
    for key, raw_val in (fields or {}).items():
        kind = EDITABLE_FIELDS.get(key)
        if kind is None:
            continue
        rhs = _format_value(kind, raw_val)
        text = _set_field(text, key, rhs)
        applied.append(key)
    if not applied:
        return {"ok": False, "msg": "no editable fields supplied"}
    mf.write_text(text, encoding="utf-8")
    return {"ok": True, "msg": f"updated {', '.join(applied)}"}


def _rename_mod(old_id: str, new_id: str) -> dict:
    """Rename mods/<old>/ -> mods/<new>/ and rewrite manifest's `id`
    field. Refuses if the target already exists."""
    if not new_id or not ID_RE.match(new_id):
        return {"ok": False, "msg": f"bad new id: {new_id!r}"}
    if not old_id or not ID_RE.match(old_id):
        return {"ok": False, "msg": f"bad old id: {old_id!r}"}
    if old_id == new_id:
        return {"ok": True, "msg": "no change"}
    src = (MODS_DIR / old_id).resolve()
    dst = (MODS_DIR / new_id).resolve()
    try:
        src.relative_to(MODS_DIR.resolve())
        dst.relative_to(MODS_DIR.resolve())
    except ValueError:
        return {"ok": False, "msg": "refusing path outside mods/"}
    if not src.is_dir():
        return {"ok": False, "msg": f"no such mod: {old_id}"}
    if dst.exists():
        return {"ok": False, "msg": f"target already exists: mods/{new_id}"}
    src.rename(dst)
    mf = dst / "manifest.toml"
    if mf.is_file():
        text = mf.read_text(encoding="utf-8")
        text = _set_field(text, "id", _toml_quote(new_id))
        mf.write_text(text, encoding="utf-8")
    return {"ok": True, "msg": f"renamed mods/{old_id} -> mods/{new_id}", "mod_id": new_id}


# ──────────────────────────────────────────────────────────────────────
# install from zip
# ──────────────────────────────────────────────────────────────────────

ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _install_zip(raw: bytes) -> dict:
    """Validate + extract a mod zip into mods/<id>/. The zip must contain
    a single top-level directory holding manifest.toml. Returns
    {ok, mod_id, msg}."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        return {"ok": False, "msg": f"not a zip file: {e}"}
    names = zf.namelist()
    if not names:
        return {"ok": False, "msg": "zip is empty"}

    # Find manifest.toml; permit either at root or nested one level deep.
    manifest_member = None
    for n in names:
        if n.endswith("manifest.toml") and n.count("/") <= 1:
            manifest_member = n
            break
    if not manifest_member:
        return {"ok": False, "msg": "no manifest.toml in zip"}

    # Determine the prefix (e.g. "MyMod/") so we know what to strip.
    prefix = ""
    if "/" in manifest_member:
        prefix = manifest_member.rsplit("/", 1)[0] + "/"

    # Parse id from manifest.
    try:
        mf_bytes = zf.read(manifest_member)
    except Exception as e:
        return {"ok": False, "msg": f"failed to read manifest: {e}"}
    from rsmm.cli.merge import _toml_load
    tmp = REPO_ROOT / ".rsmm_install_tmp.toml"
    tmp.write_bytes(mf_bytes)
    try:
        meta = _toml_load(tmp).get("mod", {})
    finally:
        try: tmp.unlink()
        except OSError: pass

    mod_id = (meta.get("id") or prefix.rstrip("/") or "").strip()
    if not mod_id or not ID_RE.match(mod_id):
        return {"ok": False,
                "msg": f"bad/missing mod id (got {mod_id!r}); must match [A-Za-z0-9_.-]+"}

    target = MODS_DIR / mod_id
    if target.exists():
        return {"ok": False, "msg": f"mod already exists: mods/{mod_id} — remove it first"}

    # Reject absolute paths or `..` traversal in zip entries.
    for n in names:
        if n.startswith("/") or ".." in Path(n).parts:
            return {"ok": False, "msg": f"refusing unsafe zip entry: {n}"}

    target.mkdir(parents=True)
    for n in names:
        if n.endswith("/"):
            continue
        rel = n[len(prefix):] if prefix and n.startswith(prefix) else n
        if not rel:
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(n) as src, open(dst, "wb") as out:
            out.write(src.read())
    return {"ok": True, "mod_id": mod_id, "msg": f"installed mods/{mod_id}"}


def _delete_mod(mod_id: str) -> dict:
    """Remove `mods/<id>/` recursively. Refuses to touch anything outside
    `mods/`."""
    if not mod_id or not ID_RE.match(mod_id):
        return {"ok": False, "msg": f"bad mod id: {mod_id!r}"}
    target = (MODS_DIR / mod_id).resolve()
    try:
        target.relative_to(MODS_DIR.resolve())
    except ValueError:
        return {"ok": False, "msg": "refusing path outside mods/"}
    if not target.is_dir():
        return {"ok": False, "msg": f"no such mod: {mod_id}"}
    import shutil
    shutil.rmtree(target)
    return {"ok": True, "msg": f"removed mods/{mod_id}"}


# ──────────────────────────────────────────────────────────────────────
# shell out to rsmm
# ──────────────────────────────────────────────────────────────────────

RSMM_PY = REPO_ROOT / "rsmm"


def _run_rsmm(subcmd_args: list[str]) -> dict:
    cmd = [sys.executable, str(RSMM_PY), *subcmd_args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(REPO_ROOT),
            timeout=600,
        )
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "rc": -1,
                "stdout": e.stdout or "", "stderr": "timeout (10 min)"}
    return {
        "ok":     proc.returncode == 0,
        "rc":     proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "cmd":    " ".join(cmd[1:]),
    }


# ──────────────────────────────────────────────────────────────────────
# SDK v3 surfaces (health / repos / update / per-mod config)
# ──────────────────────────────────────────────────────────────────────


def _health_snapshot() -> dict:
    """Return crash quarantine + boot canary + game-build pin for the GUI."""
    from rsmm.cli.apply_mods import find_game_dir
    from rsmm.sdk.health import Health
    out: dict[str, object] = {"mods": {}, "canary": None,
                              "game_build": "", "game_dir": ""}
    game = find_game_dir()
    if not game:
        return out
    cooking = game / COOKING_SUBDIR
    out["game_dir"] = str(game)
    if not cooking.is_dir():
        return out
    h = Health(cooking)
    st = h.load()
    out["threshold"] = st.threshold
    out["mods"] = {mid: {
        "crashes":            m.crashes,
        "last_error":         m.last_error,
        "last_seen":          m.last_seen,
        "disabled_by_health": m.disabled_by_health,
    } for mid, m in st.mods.items()}
    out["canary"] = h.read_canary()
    pin_file = cooking / ".rsmm_game_build.json"
    if pin_file.exists():
        try:
            raw = json.loads(pin_file.read_text(encoding="utf-8"))
            out["game_build"] = str(raw.get("sha256", ""))[:12]
        except Exception:
            pass
    return out


def _health_action(action: str, mod_id: str = "") -> dict:
    from rsmm.cli.apply_mods import find_game_dir
    from rsmm.sdk.health import Health
    game = find_game_dir()
    if not game:
        return {"ok": False, "msg": "no game install detected"}
    cooking = game / COOKING_SUBDIR
    h = Health(cooking)
    if action == "reset":
        if not mod_id:
            return {"ok": False, "msg": "missing id"}
        h.re_enable(mod_id)
        return {"ok": True, "msg": f"reset {mod_id}"}
    if action == "clear":
        st = h.load()
        for mid in list(st.mods):
            h.re_enable(mid)
        h.clear_canary()
        return {"ok": True, "msg": "cleared quarantine + canary"}
    if action == "bisect":
        from rsmm.cli.safe_mode import _bisect_step
        rc = _bisect_step(h)
        return {"ok": rc == 0, "msg": "bisect step recorded"}
    return {"ok": False, "msg": f"unknown action: {action}"}


_RSMM_HOME = Path.home() / ".rsmm"
_REPOS_FILE = _RSMM_HOME / "repos.json"


def _repos_load() -> list[str]:
    if not _REPOS_FILE.exists():
        return []
    try:
        return list(json.loads(_REPOS_FILE.read_text(encoding="utf-8"))
                    .get("urls", []))
    except Exception:
        return []


def _repos_save(urls: list[str]) -> None:
    _RSMM_HOME.mkdir(parents=True, exist_ok=True)
    _REPOS_FILE.write_text(
        json.dumps({"urls": urls}, indent=2), encoding="utf-8"
    )


def _update_check() -> dict:
    """Re-use the CLI planner without ever downloading."""
    from rsmm.cli import update_cmd
    from rsmm.sdk.repo import RepoIndex
    repos = _repos_load()
    installed = update_cmd._installed_mods()
    if not repos or not installed:
        return {"available": []}
    avail: list[dict] = []
    for url in repos:
        try:
            raw = json.loads(update_cmd._fetch(url).decode("utf-8"))
            idx = RepoIndex.load(raw)
        except Exception as e:
            avail.append({"error": f"{url}: {e}"})
            continue
        for mid, have in installed.items():
            e = idx.find(mid)
            if e and update_cmd._newer(have, e.version):
                avail.append({"id": mid, "have": have, "want": e.version,
                              "url": e.url})
    return {"available": avail}


def _set_mod_config(mod_id: str, key: str, value) -> dict:
    """Update one config field for a mod via the SDK ConfigStore."""
    if not mod_id or not ID_RE.match(mod_id):
        return {"ok": False, "msg": f"bad id: {mod_id!r}"}
    mod_dir = MODS_DIR / mod_id
    if not mod_dir.is_dir():
        return {"ok": False, "msg": f"no such mod: {mod_id}"}
    try:
        from rsmm.sdk.config import ConfigStore, ConfigError
        ConfigStore(mod_dir).set(key, value)
    except ConfigError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": True, "msg": f"set {key} = {value!r}"}


# ──────────────────────────────────────────────────────────────────────
# texture decode (optional dependency)
# ──────────────────────────────────────────────────────────────────────

_TEX_DEPS_OK: bool | None = None


def _tex_deps() -> bool:
    """Cheap presence check via `importlib.util.find_spec` so we don't
    actually import the optional decoders just to know they exist (and
    so static analysers don't flag the imports as unused)."""
    global _TEX_DEPS_OK
    if _TEX_DEPS_OK is None:
        from importlib.util import find_spec
        _TEX_DEPS_OK = (find_spec("texture2ddecoder") is not None
                        and find_spec("PIL") is not None)
    return _TEX_DEPS_OK


_ASSET_CACHE: dict[str, bytes] = {}
_AMAP_CACHE: dict[str, str] | None = None


def _amap() -> dict[str, str]:
    """decoded-lower -> encoded. Loaded once."""
    global _AMAP_CACHE
    if _AMAP_CACHE is None:
        try:
            raw = json.loads(ASSET_MAP_JSON.read_text(encoding="utf-8"))
            _AMAP_CACHE = {dec.lower(): enc for enc, dec in raw.items()}
        except Exception:
            _AMAP_CACHE = {}
    return _AMAP_CACHE


def _decode_texture(decoded_path: str) -> bytes | None:
    if decoded_path in _ASSET_CACHE:
        return _ASSET_CACHE[decoded_path]
    if not _tex_deps():
        return None
    try:
        import texture2ddecoder
        from PIL import Image
        import struct as _struct
    except ImportError:
        return None
    cooking = DEFAULT_GAME_DIR / COOKING_SUBDIR
    if not cooking.is_dir():
        return None
    base = decoded_path.replace("/", "\\")
    candidates = [base]
    if not base.lower().endswith(".texture.dxt"):
        candidates.append(base + ".Texture.dxt")
    amap = _amap()
    enc = None
    for c in candidates:
        e = amap.get(c.lower())
        if e:
            enc = e
            break
    if not enc:
        return None
    src = cooking / Path(*enc.split("\\"))
    bak = src.with_suffix(src.suffix + ".rsmm.bak")
    if bak.exists():
        src = bak
    if not src.is_file():
        return None
    raw = src.read_bytes()

    TPI_SENTINEL = bytes.fromhex(
        "2222bbaa1111bbaa00000000"
        "2222bbaa1111bbaa00000000"
    )
    s = raw.find(TPI_SENTINEL)
    if s < 0:
        return None
    off = s + len(TPI_SENTINEL)
    if off + 28 > len(raw):
        return None
    # TPI header layout: mip_count, w, h, depth, format, packed_size,
    # uncompressed_size. Only w/h/format/packed_size are needed; the
    # rest are unused (but documented here so the offset positions stay
    # legible).
    hdr = _struct.unpack_from("<7I", raw, off)
    w, h, fmt, sz1 = hdr[1], hdr[2], hdr[4], hdr[5]
    if w == 0 or h == 0:
        return None
    px = raw[off + 28: off + 28 + sz1]
    if fmt == 4:    # BC1
        rgba = texture2ddecoder.decode_bc1(px, w, h)
        img = Image.frombytes("RGBA", (w, h), rgba, "raw", "BGRA")
    elif fmt == 5:  # BC3
        rgba = texture2ddecoder.decode_bc3(px, w, h)
        img = Image.frombytes("RGBA", (w, h), rgba, "raw", "BGRA")
    elif fmt == 0 and sz1 == w * h * 4:
        img = Image.frombytes("RGBA", (w, h), px, "raw", "BGRA")
    else:
        return None
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    out = buf.getvalue()
    _ASSET_CACHE[decoded_path] = out
    return out


# ──────────────────────────────────────────────────────────────────────
# HTTP handler
# ──────────────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    server_version = "rsmm-gui/2.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[gui] %s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str,
              extra_headers: dict | None = None,
              cookies: list[str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        for c in (cookies or []):
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(body)

    # ─── auth ────────────────────────────────────────────────────────

    def _check_host(self) -> bool:
        # Reject anything not addressed to the bound localhost:port.
        # Blocks DNS rebinding + accidental external exposure.
        host = self.headers.get("Host", "")
        if host != BOUND_HOST:
            self._send(HTTPStatus.FORBIDDEN, b"host mismatch\n",
                       "text/plain; charset=utf-8")
            return False
        return True

    def _read_auth_token(self) -> str:
        # Cookie first; fall back to ?t=<token> query param so the
        # first hit (no cookie yet) can authenticate via URL.
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "rsmm_auth":
                return v
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return (q.get("t") or [""])[0]

    def _check_auth(self) -> bool:
        tok = self._read_auth_token()
        if not tok or not hmac.compare_digest(tok, AUTH_TOKEN):
            self._send(HTTPStatus.FORBIDDEN, b"auth required\n",
                       "text/plain; charset=utf-8")
            return False
        return True

    def _check_csrf(self) -> bool:
        csrf = self.headers.get("X-RSMM-CSRF", "")
        if not csrf or not hmac.compare_digest(csrf, CSRF_TOKEN):
            self._send(HTTPStatus.FORBIDDEN, b"csrf token missing\n",
                       "text/plain; charset=utf-8")
            return False
        return True

    def _auth_cookies(self) -> list[str]:
        # HttpOnly for auth (JS never needs to read it).
        # CSRF cookie is readable from JS so jpost() can echo it.
        return [
            f"rsmm_auth={AUTH_TOKEN}; Path=/; SameSite=Strict; HttpOnly",
            f"rsmm_csrf={CSRF_TOKEN}; Path=/; SameSite=Strict",
        ]

    def _send_json(self, status: int, obj: object) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"),
                   "application/json")

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _read_json(self) -> dict:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ─── routing ─────────────────────────────────────────────────────

    def do_GET(self) -> None:
        if not self._check_host():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        # /api/* always requires auth (cookie or ?t=<token>).
        if path.startswith("/api/") and not self._check_auth():
            return
        if path == "/":
            # First hit comes with ?t=<token>; if it matches, set the
            # cookies so subsequent /api/* hits don't need the query.
            cookies: list[str] = []
            tok = self._read_auth_token()
            if tok and hmac.compare_digest(tok, AUTH_TOKEN):
                cookies = self._auth_cookies()
            self._send(HTTPStatus.OK, INDEX_HTML.encode("utf-8"),
                       "text/html; charset=utf-8", cookies=cookies)
            return
        if path == "/style.css":
            self._send(HTTPStatus.OK, STYLE_CSS.encode("utf-8"),
                       "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._send(HTTPStatus.OK, APP_JS.encode("utf-8"),
                       "application/javascript; charset=utf-8")
            return
        if path == "/api/mods":
            self._send_json(HTTPStatus.OK, {"mods": _load_mods()})
            return
        if path == "/api/status":
            from rsmm.sdk.api import API_VERSION
            self._send_json(HTTPStatus.OK, {
                "game_dir":      str(DEFAULT_GAME_DIR),
                "cooking_found": (DEFAULT_GAME_DIR / COOKING_SUBDIR).is_dir(),
                "platform":      sys.platform,
                "tex_deps":      _tex_deps(),
                "repo_root":     str(REPO_ROOT),
                "sdk_version":   API_VERSION,
            })
            return
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, _health_snapshot())
            return
        if path == "/api/repos":
            self._send_json(HTTPStatus.OK, {"urls": _repos_load()})
            return
        if path == "/api/update/check":
            self._send_json(HTTPStatus.OK, _update_check())
            return
        if path.startswith("/asset/"):
            dec = urllib.parse.unquote(path[len("/asset/"):])
            png = _decode_texture(dec)
            if png is None:
                self._send(HTTPStatus.NOT_FOUND, b"", "image/png")
                return
            self._send(HTTPStatus.OK, png, "image/png",
                       extra_headers={"Cache-Control": "public, max-age=3600"})
            return
        self._send(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain")

    def do_POST(self) -> None:
        if not self._check_host():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        # All POSTs are /api/* and require both auth + CSRF.
        if not self._check_auth():
            return
        if not self._check_csrf():
            return

        if path == "/api/toggle":
            body = self._read_json()
            ok, msg = _toggle_mod(str(body.get("id") or ""),
                                  bool(body.get("enabled")))
            self._send_json(HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST,
                            {"ok": ok, "msg": msg})
            return
        if path == "/api/install":
            raw = self._read_body()
            if not raw:
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {"ok": False, "msg": "empty body"})
                return
            r = _install_zip(raw)
            self._send_json(HTTPStatus.OK if r["ok"] else HTTPStatus.BAD_REQUEST, r)
            return
        if path == "/api/delete":
            body = self._read_json()
            r = _delete_mod(str(body.get("id") or ""))
            self._send_json(HTTPStatus.OK if r["ok"] else HTTPStatus.BAD_REQUEST, r)
            return
        if path == "/api/mod-update":
            body = self._read_json()
            r = _update_mod(str(body.get("id") or ""),
                            body.get("fields") or {})
            self._send_json(HTTPStatus.OK if r["ok"] else HTTPStatus.BAD_REQUEST, r)
            return
        if path == "/api/mod-rename":
            body = self._read_json()
            r = _rename_mod(str(body.get("from") or ""),
                            str(body.get("to") or ""))
            self._send_json(HTTPStatus.OK if r["ok"] else HTTPStatus.BAD_REQUEST, r)
            return
        if path == "/api/manifest":
            # Return raw manifest text for users who want to inspect/edit
            # the full file from a textarea. Body: {"id": "..."}
            body = self._read_json()
            mid = str(body.get("id") or "")
            if not mid or not ID_RE.match(mid):
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {"ok": False, "msg": f"bad id: {mid!r}"})
                return
            mf = MODS_DIR / mid / "manifest.toml"
            if not mf.is_file():
                self._send_json(HTTPStatus.NOT_FOUND,
                                {"ok": False, "msg": f"no manifest for {mid}"})
                return
            self._send_json(HTTPStatus.OK,
                            {"ok": True, "text": mf.read_text(encoding="utf-8")})
            return
        if path == "/api/manifest-save":
            body = self._read_json()
            mid = str(body.get("id") or "")
            text = body.get("text")
            if not mid or not ID_RE.match(mid):
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {"ok": False, "msg": f"bad id: {mid!r}"})
                return
            if not isinstance(text, str):
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {"ok": False, "msg": "missing text"})
                return
            mf = MODS_DIR / mid / "manifest.toml"
            if not mf.is_file():
                self._send_json(HTTPStatus.NOT_FOUND,
                                {"ok": False, "msg": f"no manifest for {mid}"})
                return
            # Validate parse before writing. Prefer strict parsers
            # (tomllib / tomli); only the lenient repo fallback accepts
            # ill-formed input.
            try:
                try:
                    import tomllib   # Python 3.11+
                    tomllib.loads(text)
                except ImportError:
                    import tomli
                    tomli.loads(text)
            except ImportError:
                # No strict parser available — best-effort only.
                pass
            except Exception as e:
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {"ok": False, "msg": f"invalid TOML: {e}"})
                return
            mf.write_text(text, encoding="utf-8")
            self._send_json(HTTPStatus.OK,
                            {"ok": True, "msg": "manifest saved"})
            return
        if path == "/api/apply":
            self._send_json(HTTPStatus.OK, _run_rsmm(["apply"]))
            return
        if path == "/api/restore":
            self._send_json(HTTPStatus.OK, _run_rsmm(["restore", "--all"]))
            return
        if path == "/api/build":
            self._send_json(HTTPStatus.OK, _run_rsmm(["build"]))
            return
        if path == "/api/doctor":
            self._send_json(HTTPStatus.OK, _run_rsmm(["doctor"]))
            return
        if path == "/api/install-loader":
            self._send_json(HTTPStatus.OK, _run_rsmm(["install-loader"]))
            return
        if path == "/api/run":
            self._send_json(HTTPStatus.OK, _run_rsmm(["run"]))
            return
        if path == "/api/sdk-doctor":
            self._send_json(HTTPStatus.OK, _run_rsmm(["sdk-doctor"]))
            return
        if path == "/api/docs-gen":
            self._send_json(HTTPStatus.OK, _run_rsmm(["docs-gen"]))
            return

        # ─── SDK v3 endpoints ──────────────────────────────────────
        if path == "/api/mod-config":
            body = self._read_json()
            r = _set_mod_config(str(body.get("id") or ""),
                                str(body.get("key") or ""),
                                body.get("value"))
            self._send_json(HTTPStatus.OK if r["ok"] else HTTPStatus.BAD_REQUEST, r)
            return
        if path == "/api/health/reset":
            body = self._read_json()
            r = _health_action("reset", str(body.get("id") or ""))
            self._send_json(HTTPStatus.OK if r["ok"] else HTTPStatus.BAD_REQUEST, r)
            return
        if path == "/api/health/clear":
            r = _health_action("clear")
            self._send_json(HTTPStatus.OK if r["ok"] else HTTPStatus.BAD_REQUEST, r)
            return
        if path == "/api/health/bisect":
            r = _health_action("bisect")
            self._send_json(HTTPStatus.OK if r["ok"] else HTTPStatus.BAD_REQUEST, r)
            return
        if path == "/api/repos/add":
            body = self._read_json()
            url = str(body.get("url") or "").strip()
            if not url:
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {"ok": False, "msg": "url required"})
                return
            _repos_save(sorted(set(_repos_load() + [url])))
            self._send_json(HTTPStatus.OK, {"ok": True, "msg": f"added {url}"})
            return
        if path == "/api/repos/remove":
            body = self._read_json()
            url = str(body.get("url") or "")
            _repos_save([u for u in _repos_load() if u != url])
            self._send_json(HTTPStatus.OK, {"ok": True, "msg": f"removed {url}"})
            return
        if path == "/api/update":
            # --check by default for safety; explicit `apply=true` triggers
            # the actual download path via the CLI.
            body = self._read_json()
            args = ["update"]
            if not body.get("apply"):
                args.append("--check")
            else:
                args.append("--yes")
            self._send_json(HTTPStatus.OK, _run_rsmm(args))
            return

        self._send_json(HTTPStatus.NOT_FOUND,
                        {"ok": False, "msg": "no such endpoint"})


# ──────────────────────────────────────────────────────────────────────
# embedded static files
# ──────────────────────────────────────────────────────────────────────

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Ravenswatch — Mod Manager</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <img class="logo" src="/asset/Ui/MainMenu/Ravenswatch_Logo.png" alt="Ravenswatch" onerror="this.style.display='none'">
        <div class="brand-sub">Mod Manager</div>
      </div>
      <nav class="nav" id="nav">
        <button class="nav-item active" data-page="mods">
          <img class="nav-icon" src="/asset/Ui/HUD/Chest_InGame_Icon.png" alt="" onerror="this.style.display='none'">
          <span>My Mods</span>
        </button>
        <button class="nav-item" data-page="install">
          <img class="nav-icon" src="/asset/Ui/HUD/Reroll_Icon.png" alt="" onerror="this.style.display='none'">
          <span>Install</span>
        </button>
        <button class="nav-item" data-page="health">
          <img class="nav-icon" src="/asset/Ui/HUD/HUD_Health_Icon.png" alt="" onerror="this.style.display='none'">
          <span>Health</span>
        </button>
        <button class="nav-item" data-page="repos">
          <img class="nav-icon" src="/asset/Ui/HUD/HUD_Icon_Compass.png" alt="" onerror="this.style.display='none'">
          <span>Repos</span>
        </button>
        <button class="nav-item" data-page="tools">
          <img class="nav-icon" src="/asset/Ui/HUD/HUD_Attack_Power_Icon.png" alt="" onerror="this.style.display='none'">
          <span>Tools</span>
        </button>
        <button class="nav-item" data-page="settings">
          <img class="nav-icon" src="/asset/Ui/HUD/HUD_Armor_Icon.png" alt="" onerror="this.style.display='none'">
          <span>Settings</span>
        </button>
      </nav>
      <div class="sidebar-foot">
        <div class="status-dot" id="status-dot"></div>
        <div class="status-text" id="status-text">…</div>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <h1 class="page-title" id="page-title">My Mods</h1>
          <div class="page-sub" id="page-sub">Installed mods in this repository</div>
        </div>
        <div class="topbar-actions" id="topbar-actions"></div>
      </header>

      <section class="content" id="content">
        <div class="loading">loading…</div>
      </section>
    </main>
  </div>

  <script src="/app.js"></script>
</body>
</html>
"""



STYLE_CSS = r"""
/* ─── tokens — light theme ─── */
:root {
  /* Palette sampled from the game's actual book pages:
       UI_BookPageBg_L mean   = #beb39b  (parchment)
       UI_BookPageBg_01 mean  = #393325  (dark book)
       UI_Icon_Warning peaks  = #702020 / #c03030 (red)
     Surfaces stay warm + brown; accents are gold + dark red. */

  /* Parchment surfaces — page is the literal book color. */
  --bg-0:        #beb39b;  /* page (canonical parchment) */
  --bg-1:        #d4c8a8;  /* cards / brighter parchment */
  --bg-2:        #c8bb98;  /* hover */
  --bg-3:        #b0a384;  /* press / scrollbar */

  /* Dark brown for sidebar, drawers, log, brand block. */
  --dark-0:      #1f1810;
  --dark-1:      #2a2014;
  --dark-2:      #393325;  /* dark book bg */
  --dark-3:      #4a3a26;

  --line:        #8a7d62;
  --line-2:      #6b5e44;
  --line-dark:   #2a2014;

  /* Text */
  --text:        #1f1812;  /* near-black brown */
  --text-2:      #3a2e1f;
  --text-dim:    #5a4a32;
  --text-mute:   #7a6a52;
  --text-on-dark:#e8d9b4;  /* parchment-cream text on dark bars */

  /* Accent — gold like in game */
  --gold:        #b8893d;
  --gold-bright: #d4a85a;
  --gold-soft:   rgba(184,137,61,.15);
  --gold-line:   rgba(184,137,61,.45);
  --gold-deep:   #6e521f;

  /* Dark red — from game warning palette, used for danger + highlights. */
  --red:         #702020;
  --red-bright:  #a83a2a;
  --red-deep:    #4a1410;
  --red-soft:    rgba(112,32,32,.12);
  --red-line:    rgba(168,58,42,.45);

  /* Semantic */
  --ok:    #4a6a1c;
  --ok-bg: #d8d8b2;
  --bad:   var(--red);
  --bad-bg:#e8c8b8;

  --r-1: 6px;
  --r-2: 10px;
  --r-3: 14px;

  --font-sans:  'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --font-serif: 'Cinzel', 'Trajan Pro', Georgia, serif;
  --font-mono:  'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
}

* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  width: 100%; height: 100%;
  background: var(--bg-0);
  color: var(--text);
  font: 14px/1.5 var(--font-sans);
  -webkit-font-smoothing: antialiased;
  overflow: hidden;
}
a    { color: var(--gold-deep); text-decoration: none; }
code { font: 0.85em/1 var(--font-mono); background: var(--bg-2); padding: 1px 5px; border-radius: 3px; }
button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; padding: 0; }
input, textarea, select { font: inherit; color: inherit; }
::selection { background: var(--gold-bright); color: var(--text); }

.muted { color: var(--text-dim); }
.small { font-size: .8rem; }
.grow  { flex: 1; }
.grow-1{ flex: 1; }

/* ─── shell ─── */
.app {
  display: grid;
  grid-template-columns: 240px 1fr;
  height: 100vh;
}

/* Sidebar uses the dark-book brown so it reads like the spine of the
   in-game Book Menu. */
.sidebar {
  background: var(--dark-1);
  border-right: 1px solid var(--dark-0);
  display: flex; flex-direction: column;
  padding: 22px 14px 12px;
  gap: 18px;
  color: var(--text-on-dark);
}
.brand {
  padding: 12px 8px 14px;
  margin-bottom: 4px;
  text-align: center;
  border-bottom: 1px solid var(--dark-3);
}
.logo  {
  display: block;
  max-width: 168px; width: 100%;
  margin: 0 auto;
  filter: drop-shadow(0 2px 4px rgba(0,0,0,.5));
}
.brand-sub {
  margin-top: 10px;
  font: 600 .7rem/1 var(--font-serif);
  letter-spacing: .3em;
  text-transform: uppercase;
  color: var(--gold-bright);
}

.nav { display: flex; flex-direction: column; gap: 2px; }
.nav-item {
  display: flex; align-items: center; gap: 12px;
  padding: 9px 12px;
  border-radius: var(--r-1);
  color: var(--text-on-dark);
  font-size: .92rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 120ms, color 120ms;
  text-align: left;
  position: relative;
  opacity: .82;
}
.nav-item:hover {
  background: var(--dark-2);
  color: #fff5d6;
  opacity: 1;
}
.nav-item.active {
  background: var(--dark-2);
  color: var(--gold-bright);
  font-weight: 600;
  opacity: 1;
}
.nav-item.active::before {
  content: '';
  position: absolute; left: -14px; top: 8px; bottom: 8px;
  width: 3px;
  background: var(--gold);
  border-radius: 0 2px 2px 0;
  box-shadow: 0 0 8px rgba(184,137,61,.6);
}
.nav-icon {
  width: 30px; height: 30px;
  padding: 4px;
  object-fit: contain;
  flex-shrink: 0;
  background: var(--dark-0);
  border: 1px solid var(--line-2);
  border-radius: var(--r-1);
}
.nav-item.active .nav-icon {
  background: var(--dark-0);
  border-color: var(--gold);
  box-shadow: 0 0 0 1px var(--gold-line);
}

.sidebar-foot {
  margin-top: auto;
  display: flex; align-items: center; gap: 9px;
  padding: 10px 10px;
  border-top: 1px solid var(--dark-3);
  font-size: .76rem;
  color: var(--text-on-dark);
  opacity: .7;
}
.status-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--text-mute);
  flex-shrink: 0;
}
.status-dot.ok  { background: var(--ok); }
.status-dot.bad { background: var(--bad); }

/* ─── main ─── */
.main {
  display: flex; flex-direction: column;
  height: 100vh; min-width: 0; overflow: hidden;
}

/* Topbar = parchment with a red ribbon underline, like a chapter
   heading in the in-game book. */
.topbar {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 16px;
  padding: 22px 30px 18px;
  background: var(--bg-1);
  border-bottom: 2px solid var(--red);
  box-shadow: 0 1px 0 var(--gold-line);
}
.page-title {
  margin: 0;
  font: 600 1.5rem/1.2 var(--font-serif);
  letter-spacing: .02em;
  color: var(--text);
}
.page-sub {
  margin-top: 4px;
  color: var(--text-dim);
  font-size: .85rem;
}
.topbar-actions { display: flex; gap: 8px; }

.content {
  flex: 1;
  overflow-y: auto;
  padding: 26px 30px 60px;
  background: var(--bg-0);
}
.content::-webkit-scrollbar      { width: 10px; }
.content::-webkit-scrollbar-track{ background: transparent; }
.content::-webkit-scrollbar-thumb{
  background: var(--bg-3);
  border-radius: 5px;
  border: 3px solid var(--bg-0);
}
.content::-webkit-scrollbar-thumb:hover { background: var(--line-2); }

/* ─── section title ─── */
.section-title {
  margin: 0 0 14px;
  padding-bottom: 8px;
  font: 600 .82rem/1 var(--font-serif);
  letter-spacing: .22em;
  text-transform: uppercase;
  color: var(--text-dim);
  border-bottom: 1px solid var(--line);
}
.section-title--spaced { margin-top: 32px; }

/* ─── buttons ─── */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px;
  font-size: .8rem;
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--text-2);
  background: var(--bg-1);
  border: 1px solid var(--line-2);
  border-radius: var(--r-1);
  cursor: pointer;
  transition: background 120ms, border-color 120ms, color 120ms, transform 80ms;
  white-space: nowrap;
}
.btn:hover  { background: var(--bg-2); border-color: var(--gold); color: var(--text); }
.btn:active { transform: translateY(1px); }
.btn[disabled] { opacity: .55; cursor: not-allowed; }

.btn.primary {
  color: #1f1812;
  background: linear-gradient(180deg, var(--gold-bright), var(--gold));
  border-color: var(--gold-deep);
  text-shadow: 0 1px 0 rgba(255,235,180,.35);
}
.btn.primary:hover {
  background: linear-gradient(180deg, #ffd58a, var(--gold-bright));
  border-color: var(--gold);
  color: #14100b;
}
.btn.primary[disabled] { background: var(--gold); }

.btn.ghost { background: transparent; }
.btn.ghost:hover { background: var(--bg-2); }

.btn.danger {
  color: #fff;
  background: var(--red);
  border-color: var(--red-deep);
  text-shadow: 0 1px 0 rgba(0,0,0,.4);
}
.btn.danger:hover { background: var(--red-bright); border-color: var(--red); color: #fff; }

.link {
  font-size: .82rem; font-weight: 500;
  color: var(--gold-deep);
  cursor: pointer;
}
.link:hover { color: var(--gold); }

.iconbtn {
  width: 34px; height: 34px;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: var(--r-1);
  color: var(--text-dim);
  cursor: pointer;
  transition: background 120ms, color 120ms;
  background: var(--bg-1);
  border: 1px solid var(--line);
}
.iconbtn:hover { background: var(--bg-2); color: var(--text); border-color: var(--line-2); }
.iconbtn svg { width: 14px; height: 14px; }

/* ─── toolrow / search ─── */
.toolrow {
  display: flex; align-items: center; gap: 16px;
  margin-bottom: 20px;
}
.search-wrap {
  position: relative;
  flex: 1; max-width: 480px;
}
.search-ico {
  position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  width: 14px; height: 14px;
  color: var(--text-mute);
  pointer-events: none;
}
.search {
  width: 100%;
  padding: 9px 14px 9px 34px;
  background: var(--bg-1);
  border: 1px solid var(--line-2);
  border-radius: var(--r-1);
  color: var(--text);
  font-size: .9rem;
  outline: none;
  transition: border-color 120ms, background 120ms;
}
.search:focus { border-color: var(--gold); background: #fff; }
.search::placeholder { color: var(--text-mute); }

/* ─── cards ─── */
.grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
}
.card {
  display: flex; flex-direction: column;
  padding: 16px;
  background: var(--bg-1);
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  transition: border-color 120ms, transform 120ms, box-shadow 120ms;
  cursor: pointer;
  position: relative;
}
.card:hover {
  border-color: var(--gold);
  box-shadow: 0 4px 14px rgba(110,82,31,.12);
  transform: translateY(-1px);
}
.card.is-off { opacity: .6; }
.card.is-off:hover { opacity: 1; }

.card-head {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 10px;
}
.card-init {
  width: 40px; height: 40px;
  flex-shrink: 0;
  border-radius: var(--r-1);
  background: var(--gold);
  color: #fff;
  font: 700 .85rem/1 var(--font-serif);
  letter-spacing: .04em;
  display: flex; align-items: center; justify-content: center;
}
.card-title { flex: 1; min-width: 0; }
.card-name {
  font: 600 1rem/1.25 var(--font-serif);
  color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.card-sub {
  margin-top: 2px;
  font-size: .78rem;
  color: var(--text-dim);
}
.card-desc {
  margin: 0 0 12px;
  font-size: .85rem;
  color: var(--text-2);
  line-height: 1.5;
  max-height: 4.5em;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.card-desc:empty { display: none; }
.card-foot {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px;
}
.tags { display: flex; flex-wrap: wrap; gap: 4px; }
.tag {
  font: 500 .68rem/1 var(--font-sans);
  letter-spacing: .04em;
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--text-dim);
  background: var(--bg-2);
  border: 1px solid var(--line);
}
.tag.muted { color: var(--text-mute); }
.tag.on  { color: var(--gold-deep); border-color: var(--gold-line); background: var(--gold-soft); }

/* ─── toggle ─── */
.toggle {
  width: 36px; height: 20px;
  background: var(--bg-3);
  border: 1px solid var(--line-2);
  border-radius: 999px;
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 140ms, border-color 140ms;
}
.toggle::after {
  content: '';
  position: absolute; top: 2px; left: 2px;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0,0,0,.2);
  transition: left 140ms, background 140ms;
}
.toggle:hover { border-color: var(--gold); }
.toggle.on { background: var(--gold); border-color: var(--gold); }
.toggle.on::after { left: 18px; background: #fff; }

/* Editor uses same simple toggle, just larger */
.toggle-big {
  width: 52px; height: 28px;
  background: var(--bg-3);
  border: 1px solid var(--line-2);
  border-radius: 999px;
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 140ms, border-color 140ms;
}
.toggle-big::after {
  content: '';
  position: absolute; top: 2px; left: 2px;
  width: 22px; height: 22px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0,0,0,.2);
  transition: left 140ms;
}
.toggle-big:hover { border-color: var(--gold); }
.toggle-big.on { background: var(--gold); border-color: var(--gold); }
.toggle-big.on::after { left: 26px; }

/* ─── empty / loading ─── */
.loading {
  color: var(--text-dim); font-style: italic;
  padding: 24px 0; text-align: center;
}
.empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-dim);
}
.empty .empty-mark {
  width: 64px; height: 64px;
  margin: 0 auto 12px;
  border-radius: 50%;
  background: var(--bg-2);
  border: 2px solid var(--line-2);
  color: var(--gold-deep);
  font: 400 2rem/64px var(--font-serif);
}
.empty h3 {
  margin: 0 0 6px;
  font: 600 1.15rem/1 var(--font-serif);
  color: var(--text);
}
.empty p { margin: 0; font-size: .9rem; }

/* ─── pills ─── */
.pill {
  display: inline-block;
  font: 500 .68rem/1 var(--font-sans);
  letter-spacing: .04em;
  padding: 3px 8px;
  border-radius: 999px;
  margin-left: 8px;
  vertical-align: middle;
}
.pill.ok  { background: var(--ok-bg);  color: var(--ok);  border: 1px solid #c2d49a; }
.pill.bad { background: var(--bad-bg); color: var(--bad); border: 1px solid #e6b6a3; }

/* ─── dropzone ─── */
.dropzone {
  padding: 56px 24px;
  border: 2px dashed var(--line-2);
  border-radius: var(--r-2);
  background: var(--bg-1);
  text-align: center;
  cursor: pointer;
  transition: border-color 140ms, background 140ms;
}
.dropzone:hover { border-color: var(--gold); background: var(--bg-2); }
.dropzone.over  { border-color: var(--gold); background: var(--gold-soft); }
.dz-ico {
  width: 38px; height: 38px;
  color: var(--text-mute);
  margin-bottom: 10px;
}
.dropzone.over .dz-ico { color: var(--gold); }
.dropzone .big {
  font: 600 1.1rem/1.2 var(--font-serif);
  color: var(--text);
  margin-bottom: 4px;
}
.dropzone p { margin: 4px 0; font-size: .85rem; }

/* ─── tool cards ─── */
.tool-stack { display: flex; flex-direction: column; gap: 10px; }
.tool-card {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 18px;
  background: var(--bg-1);
  border: 1px solid var(--line);
  border-radius: var(--r-2);
  transition: border-color 120ms, background 120ms;
}
.tool-card:hover { border-color: var(--gold); background: var(--bg-2); }
/* Tool icons all sit in a uniform dark tile so light game art stays
   visible against the cream card surface. The PNG itself is layered
   on top of a solid backdrop. */
.tool-card .tool-icon {
  width: 52px; height: 52px;
  flex-shrink: 0;
  background-color: #1d1812;
  background-position: center;
  background-size: 36px 36px;
  background-repeat: no-repeat;
  border: 1px solid var(--line-2);
  border-radius: var(--r-1);
}
.tool-card .tool-text { flex: 1; min-width: 0; }
.tool-card h3 {
  margin: 0 0 4px;
  font: 600 1rem/1.2 var(--font-serif);
  color: var(--text);
}
.tool-card p { margin: 0; color: var(--text-dim); font-size: .85rem; }
.tool-card .snippet {
  margin: 8px 0 0;
  padding: 6px 10px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--r-1);
  font: .78rem/1.4 var(--font-mono);
  color: var(--text-2);
  width: fit-content;
}

/* ─── settings ─── */
.setting {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 24px;
  padding: 14px 0;
  border-bottom: 1px solid var(--line);
}
.setting:last-child { border-bottom: none; }
.setting .setting-text { flex: 1; min-width: 0; }
.setting .lbl {
  font-weight: 600;
  color: var(--text);
  margin-bottom: 3px;
  font-size: .9rem;
}
.setting .val {
  font: .78rem/1.4 var(--font-mono);
  background: var(--bg-2);
  border: 1px solid var(--line);
  padding: 5px 10px;
  border-radius: var(--r-1);
  color: var(--text);
  max-width: 50%;
  text-align: right;
  word-break: break-all;
}

/* ─── log ─── */
.log {
  margin: 12px 0 0;
  padding: 12px 14px;
  background: var(--dark-0);
  color: #e8d9b4;
  border: 1px solid var(--dark-3);
  border-left: 3px solid var(--red);
  border-radius: var(--r-1);
  font: .78rem/1.55 var(--font-mono);
  white-space: pre-wrap;
  max-height: 360px;
  overflow-y: auto;
}
.log:empty::before { content: '$ ready'; color: #8c815f; }

/* ─── toast ─── */
.toast {
  position: fixed;
  bottom: 24px; right: 24px;
  padding: 12px 18px;
  background: var(--bg-1);
  border: 1px solid var(--line-2);
  border-left: 3px solid var(--gold);
  border-radius: var(--r-1);
  color: var(--text);
  font-size: .88rem;
  max-width: 380px;
  box-shadow: 0 6px 18px rgba(0,0,0,.18);
  animation: toast-in 200ms ease-out;
  z-index: 80;
}
.toast.ok  { border-left-color: var(--ok); }
.toast.err { border-left-color: var(--bad); }
.toast.fade { animation: toast-out 240ms ease-in forwards; }
@keyframes toast-in  {
  from { transform: translateY(6px); opacity: 0; }
  to   { transform: translateY(0);   opacity: 1; }
}
@keyframes toast-out {
  to { transform: translateY(6px); opacity: 0; }
}

/* ─── editor drawer ─── */
.scrim {
  position: fixed; inset: 0;
  background: rgba(40,30,20,.45);
  opacity: 0;
  transition: opacity 220ms;
  z-index: 70;
}
.scrim.show { opacity: 1; }

.drawer {
  position: fixed;
  top: 0; right: 0; bottom: 0;
  width: min(580px, 92vw);
  background: var(--bg-1);
  border-left: 1px solid var(--line-2);
  display: flex; flex-direction: column;
  transform: translateX(100%);
  transition: transform 220ms cubic-bezier(.2,.7,.2,1);
  z-index: 75;
  box-shadow: -10px 0 30px rgba(40,30,20,.18);
}
.drawer.open { transform: translateX(0); }

/* Drawer head: dark book bar with parchment text + red rule. */
.drawer-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px 16px;
  background: var(--dark-1);
  border-bottom: 2px solid var(--red);
  color: var(--text-on-dark);
}
.drawer-title { display: flex; align-items: center; gap: 12px; min-width: 0; }
.drawer-title h2 {
  margin: 0;
  font: 600 1.1rem/1.2 var(--font-serif);
  color: var(--gold-bright);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 360px;
  text-shadow: 0 1px 2px rgba(0,0,0,.5);
}

.drawer-tabs {
  display: flex; gap: 4px;
  padding: 8px 16px 0;
  border-bottom: 1px solid var(--line);
  background: var(--bg-1);
}
.drawer-tab {
  padding: 9px 14px;
  font-size: .82rem; font-weight: 500;
  color: var(--text-dim);
  border-radius: var(--r-1) var(--r-1) 0 0;
  position: relative;
  cursor: pointer;
  transition: color 120ms, background 120ms;
}
.drawer-tab:hover { color: var(--text); background: var(--bg-2); }
.drawer-tab.active { color: var(--gold-deep); font-weight: 600; }
.drawer-tab.active::after {
  content: '';
  position: absolute;
  left: 10px; right: 10px; bottom: -1px;
  height: 2px; background: var(--gold);
  border-radius: 2px;
}

.drawer-body {
  flex: 1; min-height: 0;
  overflow-y: auto;
  padding: 22px;
  background: var(--bg-0);
}
.drawer-body::-webkit-scrollbar { width: 8px; }
.drawer-body::-webkit-scrollbar-thumb { background: var(--bg-3); border-radius: 4px; }
.drawer-foot {
  display: flex; align-items: center; gap: 10px;
  padding: 14px 22px;
  border-top: 1px solid var(--line);
  background: var(--bg-1);
}

/* form */
.form { display: flex; flex-direction: column; gap: 14px; }
.row { display: flex; gap: 12px; align-items: flex-start; }
.row > .field { flex: 1; min-width: 0; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field .lbl {
  font: 500 .76rem/1 var(--font-sans);
  letter-spacing: .04em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.field .hint { font-size: .78rem; color: var(--text-mute); margin-top: 2px; }

.input {
  width: 100%;
  padding: 9px 12px;
  background: var(--bg-1);
  border: 1px solid var(--line-2);
  border-radius: var(--r-1);
  color: var(--text);
  font: .9rem/1.4 var(--font-sans);
  outline: none;
  transition: border-color 120ms, background 120ms;
}
.input:focus { border-color: var(--gold); background: #fff; }
.input[type="number"] { font-variant-numeric: tabular-nums; max-width: 160px; }
textarea.input { resize: vertical; min-height: 90px; font-family: var(--font-sans); }
textarea.code {
  width: 100%;
  min-height: 360px;
  padding: 12px 14px;
  background: #1d1812;
  border: 1px solid var(--line-2);
  border-radius: var(--r-1);
  color: #d4c89a;
  font: .82rem/1.55 var(--font-mono);
  resize: vertical;
  outline: none;
  white-space: pre;
}
textarea.code:focus { border-color: var(--gold); }

.toggle-row { display: flex; align-items: center; gap: 12px; padding-top: 4px; }

.readonly {
  margin-top: 8px;
  padding: 14px 16px;
  background: var(--bg-1);
  border: 1px solid var(--line);
  border-radius: var(--r-1);
}
.readonly h4 {
  margin: 0 0 8px;
  font: 500 .72rem/1 var(--font-sans);
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.readonly .kvs {
  display: grid;
  grid-template-columns: 130px 1fr;
  gap: 5px 14px;
  font-size: .85rem;
  margin: 0;
}
.readonly .kvs dt { color: var(--text-dim); }
.readonly .kvs dd { margin: 0; color: var(--text); }

.danger-block {
  padding: 14px 16px;
  border: 1px solid var(--red-line);
  border-left: 3px solid var(--red);
  border-radius: var(--r-1);
  background: var(--red-soft);
  margin-bottom: 12px;
}
.danger-block h4 {
  margin: 0 0 4px;
  font: 600 .92rem/1.2 var(--font-serif);
  color: var(--red);
}
.danger-block p { margin: 0 0 10px; font-size: .82rem; color: var(--text-2); }
"""


APP_JS = r"""
'use strict';

const $  = (q, el=document) => el.querySelector(q);
const $$ = (q, el=document) => Array.from(el.querySelectorAll(q));

const els = {
  nav:        $('#nav'),
  pageTitle:  $('#page-title'),
  pageSub:    $('#page-sub'),
  topActions: $('#topbar-actions'),
  content:    $('#content'),
  status:     $('#status-text'),
  statusDot:  $('#status-dot'),
};

const PAGES = {
  mods:     {title: 'Mods',     sub: 'Installed mods in this repository.'},
  install:  {title: 'Install',  sub: 'Add a mod from a .zip archive.'},
  health:   {title: 'Health',   sub: 'Crash quarantine and boot canary state.'},
  repos:    {title: 'Repos',    sub: 'Configured update sources.'},
  tools:    {title: 'Tools',    sub: 'Apply, restore, build, launch.'},
  settings: {title: 'Settings', sub: 'Game install, decoder, system info.'},
};

const FIELD_LABELS = {
  name:        'Display name',
  version:     'Version',
  author:      'Author',
  description: 'Description',
  load_order:  'Load order',
  enabled:     'Enabled',
  sdk_version: 'SDK version',
};

let state = {
  page:    'mods',
  mods:    [],
  status:  null,
  search:  '',
  editing: null,    // mod id of open editor
  editTab: 'fields',// 'fields' | 'raw'
  dirty:   false,
};

// ────────────────────────────────────────────────────────────
// helpers
// ────────────────────────────────────────────────────────────

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
  })[c]);
}
function _getCookie(name) {
  const m = document.cookie.split('; ').find(c => c.startsWith(name + '='));
  return m ? m.slice(name.length + 1) : '';
}
const CSRF = _getCookie('rsmm_csrf');
async function jget(url)  { return (await fetch(url)).json(); }
async function jpost(url, body, opts={}) {
  // Always inject CSRF on top of any caller-supplied headers — the
  // server requires X-RSMM-CSRF on every POST.
  const headers = Object.assign(
    {}, opts.headers || {'Content-Type': 'application/json'},
    {'X-RSMM-CSRF': CSRF}
  );
  const r = await fetch(url, {
    method: 'POST',
    headers,
    body: opts.raw ? body : JSON.stringify(body || {}),
  });
  return r.json();
}

function initials(name) {
  return String(name || '?')
    .replace(/[^A-Za-z0-9 ]/g, '')
    .split(/\s+/).filter(Boolean).slice(0, 2)
    .map(s => s[0].toUpperCase()).join('') || '?';
}

function toast(msg, kind='') {
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.classList.add('fade'); }, 2800);
  setTimeout(() => t.remove(), 3300);
}

function setStatus(text, dotClass='') {
  els.status.textContent = text;
  els.statusDot.className = 'status-dot ' + dotClass;
}

function plural(n, one, many) { return `${n} ${n === 1 ? one : (many || one + 's')}`; }

function modById(id) { return state.mods.find(x => x.id === id || x.folder === id); }

// ────────────────────────────────────────────────────────────
// nav
// ────────────────────────────────────────────────────────────

els.nav.addEventListener('click', (e) => {
  const item = e.target.closest('.nav-item');
  if (!item) return;
  for (const b of $$('.nav-item', els.nav)) b.classList.remove('active');
  item.classList.add('active');
  state.page = item.dataset.page;
  render();
});

// ────────────────────────────────────────────────────────────
// renderers
// ────────────────────────────────────────────────────────────

function render() {
  const cfg = PAGES[state.page] || {title: '?', sub: ''};
  els.pageTitle.textContent = cfg.title;
  els.pageSub.textContent   = cfg.sub;
  els.topActions.innerHTML  = '';
  if (state.page === 'mods')     return renderMods();
  if (state.page === 'install')  return renderInstall();
  if (state.page === 'health')   return renderHealth();
  if (state.page === 'repos')    return renderRepos();
  if (state.page === 'tools')    return renderTools();
  if (state.page === 'settings') return renderSettings();
}

// ─── Mods ───────────────────────────────────────────────────

function renderMods() {
  els.topActions.innerHTML = `
    <button class="btn ghost"   data-cmd="restore">Restore</button>
    <button class="btn primary" data-cmd="apply">Apply</button>
  `;
  wireCmdButtons(els.topActions);

  const q = state.search.toLowerCase();
  const visible = !q ? state.mods : state.mods.filter(m =>
    (m.id || '').toLowerCase().includes(q) ||
    (m.name || '').toLowerCase().includes(q) ||
    (m.author || '').toLowerCase().includes(q) ||
    (m.description || '').toLowerCase().includes(q)
  );

  const enabledCount = state.mods.filter(m => m.enabled).length;
  let html = `
    <div class="toolrow">
      <div class="search-wrap">
        <svg class="search-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>
        </svg>
        <input class="search" id="search" placeholder="Filter mods by name, author, or description" value="${esc(state.search)}">
      </div>
      <div class="muted small">${plural(state.mods.length, 'mod')} · ${enabledCount} enabled</div>
    </div>
  `;

  if (!state.mods.length) {
    html += emptyState('No mods installed yet', 'Open <b>Install</b> in the sidebar to add one.');
    els.content.innerHTML = html;
    return;
  }
  if (!visible.length) {
    html += emptyState('No matches', 'Clear the search to see every mod.');
    els.content.innerHTML = html;
    wireSearch();
    return;
  }

  html += '<div class="grid">';
  for (const m of visible) {
    const tags = [];
    if (m.files_assets) tags.push(`<span class="tag">${plural(m.files_assets, 'asset')}</span>`);
    if (m.files_root)   tags.push(`<span class="tag">${m.files_root} root</span>`);
    if (m.patches)      tags.push(`<span class="tag">${plural(m.patches, 'patch','patches')}</span>`);
    if (m.has_lua)      tags.push(`<span class="tag">Lua</span>`);
    if (m.content && m.content.length)
      tags.push(`<span class="tag">${plural(m.content.length, 'content')}</span>`);
    if (m.config_schema && Object.keys(m.config_schema).length)
      tags.push(`<span class="tag">${plural(Object.keys(m.config_schema).length, 'config')}</span>`);
    if (m.locales && m.locales.length)
      tags.push(`<span class="tag">${m.locales.join(' ')}</span>`);
    if (m.sdk_version)  tags.push(`<span class="tag muted">sdk ${esc(m.sdk_version)}</span>`);

    html += `
      <article class="card ${m.enabled ? 'is-on' : 'is-off'}" data-mod="${esc(m.id)}">
        <header class="card-head">
          <div class="card-init">${esc(initials(m.name || m.id))}</div>
          <div class="card-title">
            <div class="card-name" title="${esc(m.name || m.id)}">${esc(m.name || m.id)}</div>
            <div class="card-sub">${esc(m.version || '0.0.0')}${m.author ? ' · ' + esc(m.author) : ''}</div>
          </div>
          <button class="toggle ${m.enabled ? 'on' : ''}" data-toggle="${esc(m.id)}" aria-label="toggle" title="${m.enabled?'click to disable':'click to enable'}"></button>
        </header>
        <p class="card-desc">${esc(m.description || '')}</p>
        <footer class="card-foot">
          <div class="tags">${tags.join('') || '<span class="tag muted">no files</span>'}</div>
          <button class="link" data-detail="${esc(m.id)}">Edit →</button>
        </footer>
      </article>
    `;
  }
  html += '</div>';

  els.content.innerHTML = html;
  wireSearch();

  for (const c of $$('.card', els.content)) {
    c.addEventListener('click', (ev) => {
      if (ev.target.closest('.toggle, button')) return;
      openEditor(c.dataset.mod);
    });
  }
  for (const b of $$('[data-detail]', els.content)) {
    b.addEventListener('click', (ev) => { ev.stopPropagation(); openEditor(b.dataset.detail); });
  }
  for (const t of $$('.toggle', els.content)) {
    t.addEventListener('click', (ev) => {
      ev.stopPropagation();
      toggleMod(t.dataset.toggle, t);
    });
  }
}

async function toggleMod(id, toggleEl) {
  const m = modById(id);
  if (!m) return;
  const next = !m.enabled;
  if (toggleEl) toggleEl.classList.toggle('on', next);
  const r = await jpost('/api/toggle', {id, enabled: next});
  if (!r.ok) {
    if (toggleEl) toggleEl.classList.toggle('on', !next);
    toast(r.msg || 'toggle failed', 'err');
    return;
  }
  m.enabled = next;
  const card = toggleEl ? toggleEl.closest('.card') : null;
  if (card) card.classList.toggle('is-on', next), card.classList.toggle('is-off', !next);
  toast(`${m.name || m.id} ${next ? 'enabled' : 'disabled'}`, 'ok');
}

function emptyState(title, html) {
  return `<div class="empty"><div class="empty-mark">·</div><h3>${esc(title)}</h3><p>${html}</p></div>`;
}

function wireSearch() {
  const s = $('#search');
  if (!s) return;
  s.addEventListener('input', () => {
    state.search = s.value;
    renderMods();
    requestAnimationFrame(() => {
      const ss = $('#search');
      if (ss) { ss.focus(); ss.setSelectionRange(state.search.length, state.search.length); }
    });
  });
}

// ─── Editor (drawer) ────────────────────────────────────────

async function openEditor(id) {
  const m = modById(id);
  if (!m) return;
  state.editing = m.id;
  state.editTab = 'fields';
  state.dirty = false;
  drawEditor(m);
}

function closeEditor() {
  state.editing = null;
  state.dirty = false;
  const d = $('#drawer');
  if (d) { d.classList.remove('open'); setTimeout(() => d.remove(), 220); }
  const sc = $('#scrim');
  if (sc) { sc.classList.remove('show'); setTimeout(() => sc.remove(), 220); }
}

function drawEditor(m) {
  const existing = $('#drawer'); if (existing) existing.remove();
  const existingScrim = $('#scrim'); if (existingScrim) existingScrim.remove();

  const scrim = document.createElement('div');
  scrim.id = 'scrim'; scrim.className = 'scrim';
  scrim.addEventListener('click', tryCloseEditor);
  document.body.appendChild(scrim);

  const drawer = document.createElement('aside');
  drawer.id = 'drawer';
  drawer.className = 'drawer';
  drawer.innerHTML = renderEditorBody(m);
  document.body.appendChild(drawer);

  requestAnimationFrame(() => {
    scrim.classList.add('show');
    drawer.classList.add('open');
  });

  wireEditor(m);
}

function renderEditorBody(m) {
  const tab = state.editTab;
  return `
    <header class="drawer-head">
      <div class="drawer-title">
        <div class="card-init">${esc(initials(m.name || m.id))}</div>
        <div>
          <h2>${esc(m.name || m.id)}</h2>
          <div class="muted small"><code>${esc(m.id)}</code> · <code>mods/${esc(m.folder || m.id)}/</code></div>
        </div>
      </div>
      <button class="iconbtn" id="drawer-close" aria-label="close" title="Close (Esc)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6 18 18 M18 6 6 18"/></svg>
      </button>
    </header>

    <nav class="drawer-tabs">
      <button class="drawer-tab ${tab==='fields'?'active':''}" data-tab="fields">Fields</button>
      <button class="drawer-tab ${tab==='config'?'active':''}" data-tab="config">Config</button>
      <button class="drawer-tab ${tab==='raw'?'active':''}"    data-tab="raw">Raw manifest</button>
      <button class="drawer-tab ${tab==='danger'?'active':''}" data-tab="danger">Rename &amp; delete</button>
    </nav>

    <div class="drawer-body" id="drawer-body">
      ${tab === 'fields' ? renderFieldsTab(m)
        : tab === 'config' ? renderConfigTab(m)
        : tab === 'raw' ? renderRawTab(m)
        : renderDangerTab(m)}
    </div>

    <footer class="drawer-foot" id="drawer-foot">
      ${tab === 'fields' ? `
        <span class="muted small" id="dirty-flag"></span>
        <div class="grow"></div>
        <button class="btn ghost"   id="btn-revert">Revert</button>
        <button class="btn primary" id="btn-save" disabled>Save changes</button>
      ` : tab === 'raw' ? `
        <span class="muted small">Saved as <code>mods/${esc(m.folder || m.id)}/manifest.toml</code></span>
        <div class="grow"></div>
        <button class="btn ghost"   id="btn-reload">Reload from disk</button>
        <button class="btn primary" id="btn-save-raw">Save</button>
      ` : ''}
    </footer>
  `;
}

function renderFieldsTab(m) {
  return `
    <div class="form">
      <div class="row">
        <label class="field">
          <span class="lbl">${FIELD_LABELS.name}</span>
          <input class="input" data-field="name" type="text" value="${esc(m.name || '')}" placeholder="My Mod">
        </label>
        <label class="field grow-1">
          <span class="lbl">${FIELD_LABELS.version}</span>
          <input class="input" data-field="version" type="text" value="${esc(m.version || '')}" placeholder="0.1.0">
        </label>
      </div>
      <label class="field">
        <span class="lbl">${FIELD_LABELS.author}</span>
        <input class="input" data-field="author" type="text" value="${esc(m.author || '')}" placeholder="you">
      </label>
      <label class="field">
        <span class="lbl">${FIELD_LABELS.description}</span>
        <textarea class="input" data-field="description" rows="4" placeholder="Short description shown in the mod list.">${esc(m.description || '')}</textarea>
      </label>
      <div class="row">
        <label class="field">
          <span class="lbl">${FIELD_LABELS.load_order}</span>
          <input class="input" data-field="load_order" type="number" value="${esc(m.load_order ?? 100)}" min="0" step="1">
          <span class="hint">Lower numbers load first. Default 100.</span>
        </label>
        <label class="field">
          <span class="lbl">${FIELD_LABELS.enabled}</span>
          <div class="toggle-row">
            <button class="toggle-big ${m.enabled ? 'on' : ''}" id="enabled-toggle" data-field="enabled" aria-label="enabled" title="Click to toggle"></button>
            <span id="enabled-text" class="muted small">${m.enabled ? 'Enabled in apply' : 'Disabled — skipped on apply'}</span>
          </div>
        </label>
      </div>

      <label class="field">
        <span class="lbl">${FIELD_LABELS.sdk_version}</span>
        <input class="input" data-field="sdk_version" type="text" value="${esc(m.sdk_version || '')}" placeholder=">=3.0,<4">
        <span class="hint">Semver clause(s) for the SDK API this mod targets. Loader refuses to load mismatched mods.</span>
      </label>

      <div class="readonly">
        <h4>Read-only</h4>
        <div class="kvs">
          <dt>Identifier</dt>  <dd><code>${esc(m.id)}</code></dd>
          <dt>Folder</dt>      <dd><code>mods/${esc(m.folder || m.id)}/</code></dd>
          <dt>Asset files</dt> <dd>${m.files_assets ?? 0}</dd>
          <dt>Root files</dt>  <dd>${m.files_root ?? 0}</dd>
          <dt>Patches</dt>     <dd>${m.patches ?? 0}</dd>
          <dt>Lua script</dt>  <dd>${m.has_lua ? 'present' : '—'}</dd>
          <dt>Content blocks</dt><dd>${(m.content && m.content.length) ? m.content.map(c => esc(c.kind + '/' + c.id)).join(', ') : '—'}</dd>
          <dt>Locales</dt>     <dd>${(m.locales && m.locales.length) ? esc(m.locales.join(', ')) : '—'}</dd>
        </div>
      </div>
    </div>
  `;
}

function renderConfigTab(m) {
  const schema = m.config_schema || {};
  const values = m.config_values || {};
  const fields = Object.entries(schema);
  if (m.config_error) {
    return `<div class="form"><div class="danger-block">
      <h4>Config schema error</h4>
      <p class="muted small"><code>config_schema.toml</code> failed to parse: ${esc(m.config_error)}</p>
    </div></div>`;
  }
  if (!fields.length) {
    return `<div class="form"><p class="muted small">
      This mod has no <code>config_schema.toml</code>. Add one with typed
      fields (bool / int / float / string / enum) to surface a live editor here.
    </p></div>`;
  }
  let html = `<div class="form"><p class="muted small">Edits save immediately to <code>mods/${esc(m.folder || m.id)}/config.toml</code>.</p>`;
  for (const [name, f] of fields) {
    const v = values[name];
    const label = f.label || name;
    let input;
    if (f.type === 'bool') {
      input = `<input class="cfg-input" data-cfg-key="${esc(name)}" data-cfg-type="bool" type="checkbox" ${v ? 'checked' : ''}>`;
    } else if (f.type === 'enum') {
      input = `<select class="input cfg-input" data-cfg-key="${esc(name)}" data-cfg-type="enum">`;
      for (const c of (f.choices || [])) {
        input += `<option value="${esc(c)}" ${v === c ? 'selected' : ''}>${esc(c)}</option>`;
      }
      input += '</select>';
    } else {
      const t = (f.type === 'int' || f.type === 'float') ? 'number' : 'text';
      const step = (f.type === 'float') ? 'any' : '1';
      input = `<input class="input cfg-input" data-cfg-key="${esc(name)}" data-cfg-type="${esc(f.type)}" type="${t}" step="${step}" value="${esc(v ?? '')}">`;
    }
    html += `
      <label class="field">
        <span class="lbl">${esc(label)} <code class="muted small">(${esc(f.type)})</code></span>
        ${input}
      </label>`;
  }
  html += '</div>';
  return html;
}

function wireConfigTab(m) {
  for (const inp of $$('.cfg-input')) {
    inp.addEventListener('change', async () => {
      const key  = inp.dataset.cfgKey;
      const type = inp.dataset.cfgType;
      let value;
      if (type === 'bool') value = inp.checked;
      else if (type === 'int') value = parseInt(inp.value, 10);
      else if (type === 'float') value = Number(inp.value);
      else value = inp.value;
      const r = await jpost('/api/mod-config', {id: m.id, key, value});
      toast(r.msg || (r.ok ? 'saved' : 'failed'), r.ok ? 'ok' : 'err');
      if (r.ok) {
        m.config_values = m.config_values || {};
        m.config_values[key] = value;
      }
    });
  }
}

function renderRawTab(m) {
  return `
    <div class="form">
      <p class="muted small">Edit <code>manifest.toml</code> directly. Saved value is parse-validated as TOML.</p>
      <textarea class="code" id="raw-text" spellcheck="false" placeholder="loading…"></textarea>
    </div>
  `;
}

function renderDangerTab(m) {
  return `
    <div class="form">
      <div class="danger-block">
        <h4>Rename mod folder</h4>
        <p class="muted small">Renames <code>mods/${esc(m.folder || m.id)}/</code> and rewrites the <code>id</code> field in the manifest. The mod will be tracked under its new identifier from now on.</p>
        <div class="row">
          <input class="input" id="rename-input" type="text" value="${esc(m.id)}" pattern="[A-Za-z0-9_.-]+">
          <button class="btn" id="btn-rename">Rename</button>
        </div>
      </div>

      <div class="danger-block">
        <h4>Delete from disk</h4>
        <p class="muted small">Removes <code>mods/${esc(m.folder || m.id)}/</code> and everything inside it. The applied overrides in the game install are <i>not</i> reverted — run <b>Restore</b> first if you want to roll those back.</p>
        <button class="btn danger" id="btn-delete">Delete this mod</button>
      </div>
    </div>
  `;
}

function wireEditor(m) {
  $('#drawer-close').addEventListener('click', tryCloseEditor);
  document.addEventListener('keydown', escClose);
  for (const t of $$('.drawer-tab')) {
    t.addEventListener('click', () => {
      if (state.dirty && !confirm('Discard unsaved field changes?')) return;
      state.dirty = false;
      state.editTab = t.dataset.tab;
      drawEditor(m);
    });
  }
  if (state.editTab === 'fields')      wireFieldsTab(m);
  else if (state.editTab === 'config') wireConfigTab(m);
  else if (state.editTab === 'raw')    wireRawTab(m);
  else if (state.editTab === 'danger') wireDangerTab(m);
}

function escClose(ev) { if (ev.key === 'Escape') tryCloseEditor(); }
function tryCloseEditor() {
  if (state.dirty && !confirm('Discard unsaved changes?')) return;
  document.removeEventListener('keydown', escClose);
  closeEditor();
}

function wireFieldsTab(m) {
  const inputs = $$('.input[data-field]');
  const tg = $('#enabled-toggle');
  const saveBtn = $('#btn-save');
  const revert = $('#btn-revert');
  const flag = $('#dirty-flag');

  // collect originals for revert
  const original = {
    name: m.name || '', version: m.version || '', author: m.author || '',
    description: m.description || '', load_order: m.load_order ?? 100,
    enabled: !!m.enabled, sdk_version: m.sdk_version || '',
  };
  function readCurrent() {
    const cur = {};
    for (const inp of inputs) {
      const k = inp.dataset.field;
      if (k === 'load_order') cur[k] = Number(inp.value) || 0;
      else cur[k] = inp.value;
    }
    cur.enabled = tg.classList.contains('on');
    return cur;
  }
  function refreshDirty() {
    const cur = readCurrent();
    const dirty = JSON.stringify(cur) !== JSON.stringify(original);
    state.dirty = dirty;
    saveBtn.disabled = !dirty;
    flag.textContent = dirty ? 'unsaved changes' : '';
  }

  for (const inp of inputs) inp.addEventListener('input', refreshDirty);
  tg.addEventListener('click', () => {
    tg.classList.toggle('on');
    const txt = $('#enabled-text');
    if (txt) txt.textContent = tg.classList.contains('on')
      ? 'Enabled in apply' : 'Disabled — skipped on apply';
    refreshDirty();
  });
  revert.addEventListener('click', () => {
    for (const inp of inputs) {
      const k = inp.dataset.field;
      inp.value = original[k] ?? '';
    }
    tg.classList.toggle('on', original.enabled);
    const txt = $('#enabled-text');
    if (txt) txt.textContent = original.enabled
      ? 'Enabled in apply' : 'Disabled — skipped on apply';
    refreshDirty();
  });

  saveBtn.addEventListener('click', async () => {
    const cur = readCurrent();
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    const r = await jpost('/api/mod-update', {id: m.id, fields: cur});
    saveBtn.textContent = 'Save changes';
    if (!r.ok) {
      toast(r.msg || 'save failed', 'err');
      saveBtn.disabled = false;
      return;
    }
    // Mirror to the in-memory state so the card list is consistent.
    Object.assign(m, cur);
    toast(r.msg || 'saved', 'ok');
    state.dirty = false;
    flag.textContent = 'saved';
    setTimeout(() => { if (flag) flag.textContent = ''; }, 1400);
    renderMods();
  });
}

async function wireRawTab(m) {
  const ta = $('#raw-text');
  const saveBtn = $('#btn-save-raw');
  const reload = $('#btn-reload');
  async function load() {
    ta.value = 'loading…';
    const r = await jpost('/api/manifest', {id: m.id});
    ta.value = r.ok ? r.text : `# failed to load: ${r.msg || ''}`;
  }
  await load();
  reload.addEventListener('click', load);
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    const r = await jpost('/api/manifest-save', {id: m.id, text: ta.value});
    saveBtn.textContent = 'Save'; saveBtn.disabled = false;
    if (!r.ok) { toast(r.msg || 'save failed', 'err'); return; }
    toast('manifest saved', 'ok');
    await refreshMods();
    // If the file changed scalar fields, the next openEditor will reflect them.
    renderMods();
  });
}

function wireDangerTab(m) {
  $('#btn-rename').addEventListener('click', async () => {
    const to = $('#rename-input').value.trim();
    if (!to || to === m.id) return;
    if (!/^[A-Za-z0-9_.-]+$/.test(to)) {
      toast('id must match [A-Za-z0-9_.-]+', 'err');
      return;
    }
    if (!confirm(`Rename mods/${m.id} -> mods/${to}?`)) return;
    const r = await jpost('/api/mod-rename', {from: m.id, to});
    if (!r.ok) { toast(r.msg || 'rename failed', 'err'); return; }
    toast(r.msg, 'ok');
    await refreshMods();
    closeEditor();
    state.editing = null;
    renderMods();
  });
  $('#btn-delete').addEventListener('click', async () => {
    if (!confirm(`Delete mods/${m.id}? This removes the folder from disk.`)) return;
    const r = await jpost('/api/delete', {id: m.id});
    if (!r.ok) { toast(r.msg || 'delete failed', 'err'); return; }
    toast(r.msg, 'ok');
    await refreshMods();
    closeEditor();
    renderMods();
  });
}

// ─── Install ────────────────────────────────────────────────

function renderInstall() {
  els.content.innerHTML = `
    <h2 class="section-title">Add from .zip</h2>
    <div class="dropzone" id="dropzone">
      <svg class="dz-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 3v12"/><path d="m6 9 6-6 6 6"/><path d="M5 21h14"/>
      </svg>
      <div class="big">Drop a mod zip here</div>
      <p class="muted">or click to browse your computer</p>
      <p class="muted small">The archive must contain a top-level <code>manifest.toml</code>.</p>
      <input type="file" id="filepick" accept=".zip" hidden>
    </div>
    <pre class="log" id="log-install"></pre>

    <h2 class="section-title section-title--spaced">Author your own</h2>
    <div class="tool-stack">
      <div class="tool-card">
        <div class="tool-text">
          <h3>Scaffold a new mod</h3>
          <p>Create <code>mods/&lt;id&gt;/manifest.toml</code> plus an empty <code>assets/</code> folder. Run from a terminal:</p>
          <pre class="snippet">rsmm new MyMod</pre>
        </div>
      </div>
      <div class="tool-card">
        <div class="tool-text">
          <h3>Pack for distribution</h3>
          <p>Bundle your mod into <code>dist/&lt;id&gt;.zip</code>. The packer refuses files identical to original game bytes so you never accidentally ship vanilla content.</p>
          <pre class="snippet">rsmm pack MyMod</pre>
        </div>
      </div>
    </div>
  `;
  wireDropzone();
}

function wireDropzone() {
  const dz = $('#dropzone');
  const fp = $('#filepick');
  const log = $('#log-install');
  if (!dz || !fp) return;
  dz.addEventListener('click', () => fp.click());
  fp.addEventListener('change', () => {
    if (fp.files && fp.files[0]) handleZip(fp.files[0], log);
  });
  ['dragenter', 'dragover'].forEach(t => dz.addEventListener(t, (e) => {
    e.preventDefault(); e.stopPropagation();
    dz.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(t => dz.addEventListener(t, (e) => {
    e.preventDefault(); e.stopPropagation();
    dz.classList.remove('over');
  }));
  dz.addEventListener('drop', (e) => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) handleZip(f, log);
  });
}

async function handleZip(file, logEl) {
  if (!file.name.toLowerCase().endsWith('.zip')) {
    if (logEl) logEl.textContent = `${file.name} is not a .zip`;
    toast('not a zip file', 'err');
    return;
  }
  if (logEl) logEl.textContent = `uploading ${file.name} (${file.size.toLocaleString()} bytes)…`;
  setStatus(`installing ${file.name}…`);
  const buf = await file.arrayBuffer();
  const r = await jpost('/api/install', buf, {
    raw: true,
    headers: {'Content-Type': 'application/zip'},
  });
  if (logEl) logEl.textContent = (r.ok ? '✓ ' : '✗ ') + (r.msg || '');
  toast(r.msg || (r.ok?'installed':'install failed'), r.ok ? 'ok' : 'err');
  if (r.ok) {
    await refreshMods();
    state.page = 'mods';
    for (const b of $$('.nav-item', els.nav)) b.classList.toggle('active', b.dataset.page === 'mods');
    render();
  } else {
    setStatus('install failed', 'bad');
  }
}

// ─── Health ─────────────────────────────────────────────────

async function renderHealth() {
  els.topActions.innerHTML = `
    <button class="btn ghost"   id="hbtn-bisect">Bisect step</button>
    <button class="btn primary" id="hbtn-clear">Clear all</button>
  `;
  els.content.innerHTML = '<div class="loading">loading…</div>';
  let h = {};
  try { h = await jget('/api/health'); }
  catch (e) {
    els.content.innerHTML = emptyState('Health unavailable', esc(String(e)));
    return;
  }
  const rows = Object.entries(h.mods || {});
  const canary = h.canary;
  let html = '';
  html += `<h2 class="section-title">Game build</h2>
    <div class="setting">
      <div class="setting-text">
        <div class="lbl">Pinned build hash</div>
        <div class="muted small">If this differs after a game update, mods using raw VAs may be unsafe.</div>
      </div>
      <div class="val"><code>${esc(h.game_build || '(unset)')}</code></div>
    </div>`;
  html += `<h2 class="section-title section-title--spaced">Boot canary</h2>`;
  if (canary) {
    html += `<div class="setting">
      <div class="setting-text">
        <div class="lbl"><span class="pill bad">stale canary</span></div>
        <div class="muted small">Last step before crash: <code>${esc(canary.last_step || '?')}</code>.
          Run <b>Bisect step</b> to narrow the culprit, or <b>Clear all</b> to start fresh.</div>
      </div>
    </div>`;
  } else {
    html += `<div class="setting">
      <div class="setting-text">
        <div class="lbl"><span class="pill ok">clean</span></div>
        <div class="muted small">Last shutdown was clean — no boot canary on disk.</div>
      </div>
    </div>`;
  }
  html += `<h2 class="section-title section-title--spaced">Crash records</h2>`;
  if (!rows.length) {
    html += emptyState('No crash records', 'Mods that throw inside their lifecycle get tallied here. Three strikes = auto-disabled.');
  } else {
    html += '<div class="tool-stack">';
    for (const [mid, v] of rows) {
      const status = v.disabled_by_health
        ? '<span class="pill bad">DISABLED</span>'
        : '<span class="pill ok">ok</span>';
      html += `
        <div class="tool-card">
          <div class="tool-text">
            <h3>${esc(mid)}  ${status}</h3>
            <p>${esc(v.crashes)} crash${v.crashes === 1 ? '' : 'es'}${v.last_error ? ' · ' + esc(v.last_error.slice(0, 200)) : ''}</p>
          </div>
          <button class="btn ghost" data-hreset="${esc(mid)}">Reset</button>
        </div>`;
    }
    html += '</div>';
  }
  els.content.innerHTML = html;

  $('#hbtn-clear').addEventListener('click', async () => {
    if (!confirm('Clear quarantine + boot canary for every mod?')) return;
    const r = await jpost('/api/health/clear', {});
    toast(r.msg || (r.ok ? 'cleared' : 'failed'), r.ok ? 'ok' : 'err');
    renderHealth();
  });
  $('#hbtn-bisect').addEventListener('click', async () => {
    const r = await jpost('/api/health/bisect', {});
    toast(r.msg || (r.ok ? 'bisect step' : 'failed'), r.ok ? 'ok' : 'err');
    renderHealth();
  });
  for (const b of $$('[data-hreset]', els.content)) {
    b.addEventListener('click', async () => {
      const r = await jpost('/api/health/reset', {id: b.dataset.hreset});
      toast(r.msg || (r.ok ? 'reset' : 'failed'), r.ok ? 'ok' : 'err');
      renderHealth();
    });
  }
}

// ─── Repos ──────────────────────────────────────────────────

async function renderRepos() {
  els.topActions.innerHTML = `<button class="btn primary" id="rbtn-check">Check for updates</button>`;
  els.content.innerHTML = '<div class="loading">loading…</div>';
  let d = {urls: []};
  try { d = await jget('/api/repos'); }
  catch (e) {
    els.content.innerHTML = emptyState('Repos unavailable', esc(String(e)));
    return;
  }
  let html = `
    <h2 class="section-title">Add a repository</h2>
    <div class="form">
      <div class="row">
        <input class="input grow-1" id="repo-url" type="text"
               placeholder="https://example.com/repo.json">
        <button class="btn primary" id="repo-add">Add</button>
      </div>
      <div class="muted small">Open spec: each repo is a static <code>repo.json</code> hosted anywhere
        (GitHub Pages, S3, your own server). Signed mods are silently installed;
        unsigned ones prompt for confirmation.</div>
    </div>

    <h2 class="section-title section-title--spaced">Configured (${d.urls.length})</h2>`;
  if (!d.urls.length) {
    html += emptyState('No repositories yet', 'Add a <code>repo.json</code> URL above to enable update checks.');
  } else {
    html += '<div class="tool-stack">';
    for (const u of d.urls) {
      html += `
        <div class="tool-card">
          <div class="tool-text">
            <h3><code>${esc(u)}</code></h3>
          </div>
          <button class="btn ghost" data-rrem="${esc(u)}">Remove</button>
        </div>`;
    }
    html += '</div>';
  }
  html += `<h2 class="section-title section-title--spaced">Output</h2>
    <pre class="log" id="log-repos"></pre>`;
  els.content.innerHTML = html;

  $('#repo-add').addEventListener('click', async () => {
    const url = $('#repo-url').value.trim();
    if (!url) return;
    const r = await jpost('/api/repos/add', {url});
    toast(r.msg || (r.ok ? 'added' : 'failed'), r.ok ? 'ok' : 'err');
    renderRepos();
  });
  for (const b of $$('[data-rrem]', els.content)) {
    b.addEventListener('click', async () => {
      const r = await jpost('/api/repos/remove', {url: b.dataset.rrem});
      toast(r.msg || (r.ok ? 'removed' : 'failed'), r.ok ? 'ok' : 'err');
      renderRepos();
    });
  }
  $('#rbtn-check').addEventListener('click', async () => {
    const log = $('#log-repos');
    log.textContent = 'checking…';
    try {
      const r = await jget('/api/update/check');
      const avail = (r.available || []).filter(x => x.id);
      const errs  = (r.available || []).filter(x => x.error);
      if (!avail.length && !errs.length) {
        log.textContent = 'everything up to date';
      } else {
        const lines = [];
        if (avail.length) {
          lines.push(`Updates available (${avail.length}):`);
          for (const a of avail) lines.push(`  ${a.id}: ${a.have} -> ${a.want}  (${a.url})`);
        }
        if (errs.length) {
          lines.push('Errors:');
          for (const e of errs) lines.push('  ' + e.error);
        }
        log.textContent = lines.join('\n');
      }
      toast('checked', 'ok');
    } catch (e) {
      log.textContent = String(e);
      toast('check failed', 'err');
    }
  });
}

// ─── Tools ──────────────────────────────────────────────────

function renderTools() {
  const tools = [
    {cmd: 'apply',          title: 'Apply mods',         desc: 'Copy enabled mods into the game install. Backs up originals as <code>.rsmm.bak</code>.', primary: true, group: 'Daily',
     icon: '/asset/Ui/HUD/HUD_Checkbox_Check_TRUE.png'},
    {cmd: 'restore',        title: 'Restore all',        desc: 'Undo every applied override. Mod files stay on disk.', group: 'Daily',
     icon: '/asset/Ui/HUD/HUD_Revive_Feather_Icon.png'},
    {cmd: 'run',            title: 'Launch game',        desc: 'Open Ravenswatch via Steam.', primary: true, group: 'Daily',
     icon: '/asset/Ui/HUD/HUD_Icon_Jack.png'},
    {cmd: 'build',          title: 'Full build',         desc: 'Asset map + loader DLL + patch-merge + apply, in one shot.', group: 'Setup',
     icon: '/asset/Ui/HUD/Chest_InGame_Icon.png'},
    {cmd: 'install-loader', title: 'Install loader DLL', desc: 'Drop <code>winhttp.dll</code> into the game directory. Needed only for Lua mods.', group: 'Setup',
     icon: '/asset/Ui/HUD/Buff_Shield_Icon.png'},
    {cmd: 'doctor',         title: 'Run doctor',         desc: 'Health check: asset map, loader, mods, patch conflicts, compat graph.', group: 'Setup',
     icon: '/asset/Ui/HUD/HUD_Icon_Eye.png'},
    {cmd: 'sdk-doctor',     title: 'SDK doctor',         desc: 'Inspect plugin registry, per-mod schema validity, i18n coverage, game-build pin.', group: 'Setup',
     icon: '/asset/Ui/HUD/HUD_Icon_Eye.png'},
    {cmd: 'docs-gen',       title: 'Regenerate API docs', desc: 'Write <code>docs/api/*.md</code> from every <code>@sdk_export</code> registration in the SDK.', group: 'Setup',
     icon: '/asset/Ui/HUD/Tutorial_Icon.png'},
  ];
  const groups = ['Daily', 'Setup'];
  let html = '';
  for (const g of groups) {
    html += `<h2 class="section-title ${g === 'Daily' ? '' : 'section-title--spaced'}">${g}</h2>`;
    html += '<div class="tool-stack">';
    for (const t of tools.filter(x => x.group === g)) {
      html += `
        <div class="tool-card">
          <div class="tool-icon" style="background-image:url('${esc(t.icon)}')"></div>
          <div class="tool-text">
            <h3>${esc(t.title)}</h3>
            <p>${t.desc}</p>
          </div>
          <button class="btn ${t.primary ? 'primary' : 'ghost'}" data-cmd="${esc(t.cmd)}">Run</button>
        </div>`;
    }
    html += '</div>';
  }
  html += '<h2 class="section-title section-title--spaced">Output</h2><pre class="log" id="log-tools"></pre>';
  els.content.innerHTML = html;
  wireCmdButtons(els.content, 'log-tools');
}

// ─── Settings ───────────────────────────────────────────────

function renderSettings() {
  const s = state.status || {};
  els.content.innerHTML = `
    <h2 class="section-title">Game install</h2>
    <div class="setting">
      <div class="setting-text">
        <div class="lbl">Detected directory ${s.cooking_found
          ? '<span class="pill ok">cooked assets found</span>'
          : '<span class="pill bad">_Cooking missing</span>'}</div>
        <div class="muted small">If autodetection picked the wrong path, pass <code>--game-dir &lt;path&gt;</code> to any rsmm subcommand.</div>
      </div>
      <div class="val">${esc(s.game_dir || '(unset)')}</div>
    </div>
    <div class="setting">
      <div class="setting-text">
        <div class="lbl">Platform</div>
        <div class="muted small">Operating system reported by Python.</div>
      </div>
      <div class="val">${esc(s.platform || '?')}</div>
    </div>
    <div class="setting">
      <div class="setting-text">
        <div class="lbl">Repository root</div>
        <div class="muted small">Where this rsmm checkout lives.</div>
      </div>
      <div class="val">${esc(s.repo_root || '?')}</div>
    </div>

    <h2 class="section-title section-title--spaced">Texture decoder</h2>
    <div class="setting">
      <div class="setting-text">
        <div class="lbl">Status ${s.tex_deps ? '<span class="pill ok">enabled</span>' : '<span class="pill bad">missing</span>'}</div>
        <div class="muted small">
          ${s.tex_deps
            ? 'Game icons and the Ravenswatch logo are decoded live from your install.'
            : 'Install the optional decoders to pull live game icons: <code>pip install --user texture2ddecoder Pillow</code>'}
        </div>
      </div>
      <div class="val">texture2ddecoder + Pillow</div>
    </div>

    <h2 class="section-title section-title--spaced">SDK</h2>
    <div class="setting">
      <div class="setting-text">
        <div class="lbl">API version</div>
        <div class="muted small">Mods declare <code>sdk_version</code> in their manifest; loader gates on this clause.</div>
      </div>
      <div class="val">${esc(s.sdk_version || '?')}</div>
    </div>

    <h2 class="section-title section-title--spaced">About</h2>
    <div class="setting">
      <div class="setting-text">
        <div class="lbl">Ravenswatch Mod Manager</div>
        <div class="muted small">Local web UI. Server binds to <code>127.0.0.1</code> only — nobody else on your network can reach it.</div>
      </div>
      <div class="val">${esc(location.host)}</div>
    </div>
  `;
}

// ─── shared: command buttons ────────────────────────────────

function wireCmdButtons(scope, logId) {
  for (const b of $$('.btn[data-cmd]', scope)) {
    b.addEventListener('click', () => runCmd(b.dataset.cmd, b, logId || 'log-tools'));
  }
}

async function runCmd(cmd, btn, logId) {
  const logEl = document.getElementById(logId);
  if (btn) btn.setAttribute('disabled', 'true');
  const oldLabel = btn ? btn.textContent : '';
  if (btn) btn.textContent = 'Running…';
  if (logEl) logEl.textContent = `$ rsmm ${cmd}\n…`;
  setStatus(`running ${cmd}…`, '');
  const r = await jpost('/api/' + cmd, {});
  let out = '';
  if (r.cmd)    out += `$ ${r.cmd}\n\n`;
  if (r.stdout) out += r.stdout;
  if (r.stderr) out += '\n--- stderr ---\n' + r.stderr;
  out += `\n(exit ${r.rc})`;
  if (logEl) logEl.textContent = out;
  if (btn) { btn.removeAttribute('disabled'); btn.textContent = oldLabel; }
  toast(`${cmd} ${r.ok ? 'ok' : 'failed'}`, r.ok ? 'ok' : 'err');
  setStatus(r.ok ? `${cmd} ok` : `${cmd} failed`, r.ok ? 'ok' : 'bad');
  if (['apply','restore','build'].includes(cmd)) await refreshMods();
  if (state.page === 'mods') renderMods();
}

// ────────────────────────────────────────────────────────────
// boot
// ────────────────────────────────────────────────────────────

async function refreshMods() {
  const r = await jget('/api/mods');
  state.mods = r.mods || [];
}
async function refreshStatus() {
  state.status = await jget('/api/status');
}

async function boot() {
  await Promise.all([refreshStatus(), refreshMods()]);
  const ok = state.status && state.status.cooking_found;
  setStatus(
    ok ? `${plural(state.mods.length, 'mod')} · ${state.status.platform}` : 'game install not found',
    ok ? 'ok' : 'bad',
  );
  render();
}
boot().catch(err => {
  els.content.innerHTML = `<div class="empty"><h3>Failed to load</h3><p>${esc(String(err))}</p></div>`;
});

"""


# ──────────────────────────────────────────────────────────────────────
# server bootstrap
# ──────────────────────────────────────────────────────────────────────

def _pick_port(preferred: int = 0) -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", preferred))
        return s.getsockname()[1]
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Open the rsmm web UI")
    ap.add_argument("--port", type=int, default=0,
                    help="listen on this port (default: OS-assigned)")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't auto-open the browser")
    args = ap.parse_args()

    global AUTH_TOKEN, CSRF_TOKEN, BOUND_HOST
    AUTH_TOKEN = secrets.token_urlsafe(32)
    CSRF_TOKEN = secrets.token_urlsafe(16)

    port = _pick_port(args.port)
    BOUND_HOST = f"127.0.0.1:{port}"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://{BOUND_HOST}/?t={AUTH_TOKEN}"
    print(f"rsmm gui listening at http://{BOUND_HOST}/")
    # Token only printed to stderr — keeps it out of stdout pipes /
    # captured logs by accident, and matches the pattern used by
    # `jupyter notebook` and friends.
    print(f"  one-shot auth URL: {url}", file=sys.stderr)
    print("Ctrl-C to quit.")

    if not args.no_browser:
        threading.Thread(
            target=lambda: (time.sleep(0.4), webbrowser.open(url)),
            daemon=True,
        ).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())