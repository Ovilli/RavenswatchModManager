#!/usr/bin/env python3
"""`rsmm gui` — local web app for non-CLI users.

Serves a self-contained mod manager on http://127.0.0.1:<port>/ with a
random auth token in the URL. Opens the user's default browser.

Tabs:
  * Mods      — enable/disable + per-mod config editor + apply button
  * Health    — crash quarantine, boot canary, safe-mode controls
  * Repos     — add/remove repo URLs, check + apply updates
  * Logs      — live tail of the loader log

Security (matches the prior `sec(gui)` commit posture):
  * Bound to 127.0.0.1 only — never reachable over the network.
  * Mandatory auth token in the URL on first hit; stored in a cookie.
  * `Host:` header must match `127.0.0.1:<port>` or `localhost:<port>`
    to defeat DNS-rebind attacks from a malicious page in the browser.
  * Every POST requires an `X-CSRF-Token` header matching the token
    issued with the page (returned in the initial HTML as a meta tag).

Stdlib-only. No npm, no pip install.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import socket
import sys
import threading
import tomllib
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from rsmm.engine.paths import MODS_DIR, COOKING_SUBDIR
from rsmm.cli.apply_mods import find_game_dir
from rsmm.sdk.api import API_VERSION
from rsmm.sdk.config import ConfigStore, ConfigError
from rsmm.sdk.health import Health
from rsmm.sdk.i18n import I18nBundle


# ---------------------------------------------------------------------------
# Auth / CSRF
# ---------------------------------------------------------------------------

AUTH_TOKEN = secrets.token_urlsafe(24)
CSRF_TOKEN = secrets.token_urlsafe(16)

ALLOWED_HOSTS: set[str] = set()  # populated at startup with 127.0.0.1:<port>


def _check_auth(req: BaseHTTPRequestHandler) -> bool:
    """Token must arrive via cookie OR ?token=... query param. The
    handler sets the cookie on the first authenticated GET."""
    cookies = req.headers.get("Cookie", "")
    for c in cookies.split(";"):
        k, _, v = c.strip().partition("=")
        if k == "rsmm_token" and v == AUTH_TOKEN:
            return True
    qs = parse_qs(urlsplit(req.path).query)
    return qs.get("token", [""])[0] == AUTH_TOKEN


def _check_host(req: BaseHTTPRequestHandler) -> bool:
    host = req.headers.get("Host", "")
    return host in ALLOWED_HOSTS


def _check_csrf(req: BaseHTTPRequestHandler) -> bool:
    return req.headers.get("X-CSRF-Token", "") == CSRF_TOKEN


# ---------------------------------------------------------------------------
# Mod model
# ---------------------------------------------------------------------------


def _read_mods() -> list[dict[str, Any]]:
    """Snapshot every mod's manifest + config schema/values + i18n."""
    out: list[dict[str, Any]] = []
    if not MODS_DIR.is_dir():
        return out
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        mf = entry / "manifest.toml"
        if not mf.exists():
            continue
        try:
            tbl = tomllib.loads(mf.read_text(encoding="utf-8"))
        except Exception as e:
            out.append({"id": entry.name, "error": f"manifest parse: {e}"})
            continue
        meta = tbl.get("mod") or {}
        item: dict[str, Any] = {
            "id": str(meta.get("id", entry.name)),
            "name": str(meta.get("name", entry.name)),
            "version": str(meta.get("version", "0.0.0")),
            "author": str(meta.get("author", "")),
            "description": str(meta.get("description", "")),
            "enabled": bool(meta.get("enabled", True)),
            "sdk_version": str(meta.get("sdk_version", "")),
            "has_init_lua": (entry / "init.lua").is_file(),
            "content": list(tbl.get("content") or []),
        }
        try:
            store = ConfigStore(entry)
            item["config_schema"] = {
                name: {
                    "type": f.type,
                    "default": f.default,
                    "min": f.min, "max": f.max,
                    "choices": f.choices, "label": f.label,
                }
                for name, f in store.schema.fields.items()
            }
            item["config_values"] = store.all()
        except ConfigError as e:
            item["config_error"] = str(e)
        try:
            b = I18nBundle.load(item["id"], entry)
            item["locales"] = sorted(b.by_locale.keys())
        except Exception as e:
            item["i18n_error"] = str(e)
        out.append(item)
    return out


_ENABLED_RE = re.compile(
    r"^(\s*enabled\s*=\s*)(true|false)\s*$", re.IGNORECASE | re.MULTILINE,
)


def _set_enabled(mod_id: str, enabled: bool) -> bool:
    """Flip the `enabled` field of one manifest in place."""
    mf = MODS_DIR / mod_id / "manifest.toml"
    if not mf.exists():
        return False
    txt = mf.read_text(encoding="utf-8")
    new = "true" if enabled else "false"
    out, n = _ENABLED_RE.subn(rf"\g<1>{new}", txt, count=1)
    if n == 0:
        # No enabled line — append to [mod] block.
        out = re.sub(
            r"(\[mod\][^\[]*)", rf"\1enabled = {new}\n", txt, count=1, flags=re.DOTALL,
        )
        if out == txt:
            return False
    mf.write_text(out, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# HTML payload
# ---------------------------------------------------------------------------


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>RSMM</title>
<meta name="csrf" content="__CSRF__">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {
  --bg:#0d1117; --panel:#161b22; --line:#30363d; --fg:#e6edf3;
  --muted:#8b949e; --accent:#d28a2a; --ok:#3fb950; --bad:#f85149;
  --code:#1f2428;
}
* { box-sizing: border-box; }
html, body { margin:0; padding:0; background:var(--bg); color:var(--fg);
  font-family: ui-sans-serif, system-ui, "Segoe UI", sans-serif; }
header { padding:14px 20px; border-bottom:1px solid var(--line);
  display:flex; align-items:center; gap:18px; background:var(--panel); }
header h1 { margin:0; font-size:17px; letter-spacing:1px; color:var(--accent); }
nav { display:flex; gap:6px; }
nav button { background:transparent; color:var(--fg); border:1px solid var(--line);
  padding:6px 14px; cursor:pointer; border-radius:6px; font-size:13px; }
nav button.active { background:var(--accent); color:#000; border-color:var(--accent); }
main { padding:16px 20px 60px 20px; max-width:1100px; margin:0 auto; }
.tab { display:none; }
.tab.active { display:block; }
.mod { background:var(--panel); border:1px solid var(--line); border-radius:8px;
  padding:14px 16px; margin-bottom:12px; }
.mod h2 { margin:0 0 4px 0; font-size:15px; }
.mod .meta { color:var(--muted); font-size:12px; margin-bottom:8px; }
.mod .desc { font-size:13px; margin:6px 0 10px 0; }
.row { display:flex; align-items:center; gap:10px; }
.row.right { justify-content:flex-end; }
.toggle { padding:5px 12px; border-radius:4px; cursor:pointer; border:1px solid var(--line);
  background:var(--code); color:var(--fg); font-size:12px; }
.toggle.on { background:var(--ok); color:#000; border-color:var(--ok); }
.toggle.off { background:#21262d; }
.field { display:grid; grid-template-columns:160px 1fr; gap:8px; padding:6px 0;
  align-items:center; border-top:1px dashed var(--line); }
.field label { color:var(--muted); font-size:12px; }
.field input, .field select { background:var(--code); color:var(--fg);
  border:1px solid var(--line); border-radius:4px; padding:5px 8px; font-size:13px; }
button.primary { background:var(--accent); color:#000; border:0; padding:8px 18px;
  border-radius:6px; cursor:pointer; font-weight:600; }
button.secondary { background:var(--code); color:var(--fg); border:1px solid var(--line);
  padding:6px 12px; border-radius:6px; cursor:pointer; }
button.bad { background:var(--bad); color:#fff; border:0; padding:6px 12px;
  border-radius:6px; cursor:pointer; }
.toolbar { margin-bottom:14px; }
pre.log { background:#0a0f15; border:1px solid var(--line); padding:10px;
  border-radius:6px; max-height:60vh; overflow:auto; font-size:12px;
  white-space:pre-wrap; word-break:break-all; }
input.url { width:100%; }
.status-ok { color:var(--ok); }
.status-bad { color:var(--bad); }
.muted { color:var(--muted); font-size:12px; }
table { border-collapse: collapse; width:100%; }
table th, table td { text-align:left; padding:6px 8px;
  border-bottom:1px solid var(--line); font-size:13px; }
table th { color:var(--muted); font-weight:500; }
.badge { display:inline-block; padding:1px 8px; border-radius:99px; font-size:11px;
  border:1px solid var(--line); color:var(--muted); }
.badge.on { color:var(--ok); border-color:var(--ok); }
.badge.off { color:var(--muted); }
.toast { position:fixed; right:18px; bottom:18px; background:var(--panel);
  border:1px solid var(--line); padding:10px 14px; border-radius:6px;
  box-shadow:0 4px 16px rgba(0,0,0,0.4); display:none; max-width:360px; font-size:13px; }
.toast.show { display:block; }
.toast.bad { border-color:var(--bad); }
</style>
</head>
<body>
<header>
  <h1>RSMM &nbsp;<span class="muted" style="font-weight:400">SDK v__API__</span></h1>
  <nav>
    <button data-tab="mods" class="active">Mods</button>
    <button data-tab="health">Health</button>
    <button data-tab="repos">Repos</button>
    <button data-tab="logs">Logs</button>
  </nav>
  <div style="flex:1"></div>
  <button class="primary" id="apply-btn">Apply</button>
</header>
<main>
  <section id="tab-mods" class="tab active"></section>
  <section id="tab-health" class="tab"></section>
  <section id="tab-repos" class="tab"></section>
  <section id="tab-logs" class="tab"></section>
</main>
<div class="toast" id="toast"></div>
<script>
const CSRF = document.querySelector("meta[name=csrf]").content;

function toast(msg, bad) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show" + (bad ? " bad" : "");
  setTimeout(() => t.className = "toast", 3500);
}

async function api(path, opts) {
  opts = opts || {};
  opts.headers = Object.assign({ "X-CSRF-Token": CSRF,
    "Content-Type": "application/json" }, opts.headers || {});
  const r = await fetch(path, opts);
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}

function el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  for (const k in attrs || {}) {
    if (k === "class") e.className = attrs[k];
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), attrs[k]);
    else e.setAttribute(k, attrs[k]);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

// ---- Tabs ----
document.querySelectorAll("nav button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("nav button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.getElementById("tab-" + b.dataset.tab).classList.add("active");
    if (b.dataset.tab === "health") loadHealth();
    if (b.dataset.tab === "repos") loadRepos();
    if (b.dataset.tab === "logs") loadLog();
  };
});

// ---- Mods tab ----
async function loadMods() {
  const data = await api("/api/mods");
  const sec = document.getElementById("tab-mods");
  sec.innerHTML = "";
  if (!data.mods.length) {
    sec.appendChild(el("p", { class:"muted" }, "No mods found under mods/."));
    return;
  }
  for (const m of data.mods) {
    const card = el("div", { class:"mod" });
    const head = el("div", { class:"row" });
    head.appendChild(el("h2", {}, m.name + "  "));
    head.appendChild(el("span", { class:"badge " + (m.enabled?"on":"off") },
      m.enabled ? "enabled" : "disabled"));
    if (m.sdk_version) head.appendChild(el("span", { class:"badge" }, "sdk " + m.sdk_version));
    head.appendChild(el("div", { style:"flex:1" }));
    const tog = el("button", {
      class:"toggle " + (m.enabled?"on":"off"),
      onclick: async () => {
        try {
          await api("/api/mod/toggle", { method:"POST",
            body: JSON.stringify({ id: m.id, enabled: !m.enabled }) });
          loadMods();
        } catch (e) { toast(e.message, true); }
      },
    }, m.enabled ? "Disable" : "Enable");
    head.appendChild(tog);
    card.appendChild(head);
    card.appendChild(el("div", { class:"meta" },
      `id=${m.id} · v${m.version} · by ${m.author || "unknown"}`));
    if (m.description) card.appendChild(el("div", { class:"desc" }, m.description));
    if (m.error) card.appendChild(el("div", { class:"status-bad" }, m.error));

    // Config schema
    if (m.config_schema && Object.keys(m.config_schema).length) {
      card.appendChild(el("div", { class:"muted" }, "Config:"));
      for (const [name, f] of Object.entries(m.config_schema)) {
        const wrap = el("div", { class:"field" });
        wrap.appendChild(el("label", {}, f.label || name));
        let input;
        if (f.type === "bool") {
          input = el("input", { type:"checkbox" });
          if (m.config_values[name]) input.checked = true;
        } else if (f.type === "enum") {
          input = el("select");
          for (const c of f.choices) {
            const opt = el("option", { value: c }, c);
            if (m.config_values[name] === c) opt.selected = true;
            input.appendChild(opt);
          }
        } else {
          input = el("input", { type: (f.type==="int"||f.type==="float")?"number":"text" });
          if (m.config_values[name] != null) input.value = m.config_values[name];
        }
        input.onchange = async () => {
          const val = (f.type==="bool") ? input.checked
                    : (f.type==="int" || f.type==="float") ? Number(input.value)
                    : input.value;
          try {
            await api("/api/mod/config", { method:"POST",
              body: JSON.stringify({ id:m.id, key:name, value:val }) });
            toast(`set ${name} = ${val}`);
          } catch (e) { toast(e.message, true); }
        };
        wrap.appendChild(input);
        card.appendChild(wrap);
      }
    }
    if (m.locales && m.locales.length) {
      card.appendChild(el("div", { class:"muted" },
        "Locales: " + m.locales.join(", ")));
    }
    if (m.content && m.content.length) {
      card.appendChild(el("div", { class:"muted" },
        "Content: " + m.content.map(c => `${c.kind}/${c.id}`).join(", ")));
    }
    sec.appendChild(card);
  }
}

document.getElementById("apply-btn").onclick = async () => {
  try {
    toast("running rsmm apply...");
    const r = await api("/api/apply", { method:"POST", body:"{}" });
    toast(r.ok ? "apply complete" : ("apply: " + r.message), !r.ok);
  } catch (e) { toast(e.message, true); }
};

// ---- Health ----
async function loadHealth() {
  const sec = document.getElementById("tab-health");
  sec.innerHTML = "Loading...";
  try {
    const h = await api("/api/health");
    sec.innerHTML = "";
    const tbar = el("div", { class:"toolbar row" });
    tbar.appendChild(el("button", { class:"secondary", onclick: async () => {
      await api("/api/health/clear", { method:"POST", body:"{}" });
      loadHealth();
    } }, "Clear quarantine + canary"));
    tbar.appendChild(el("button", { class:"secondary", onclick: async () => {
      await api("/api/health/bisect", { method:"POST", body:"{}" });
      loadHealth();
    } }, "Bisect step"));
    sec.appendChild(tbar);
    if (h.canary) {
      sec.appendChild(el("p", { class:"status-bad" },
        "Stale boot canary: last_step=" + (h.canary.last_step || "?")));
    } else {
      sec.appendChild(el("p", { class:"status-ok" }, "No boot canary — clean shutdown."));
    }
    sec.appendChild(el("p", { class:"muted" }, "Build: " + (h.game_build || "unknown")));
    const tbl = el("table");
    const thead = el("thead"); const trh = el("tr");
    trh.appendChild(el("th", {}, "Mod"));
    trh.appendChild(el("th", {}, "Crashes"));
    trh.appendChild(el("th", {}, "Status"));
    trh.appendChild(el("th", {}, "Last error"));
    trh.appendChild(el("th", {}, ""));
    thead.appendChild(trh);
    tbl.appendChild(thead);
    const tb = el("tbody");
    for (const [mid, v] of Object.entries(h.mods || {})) {
      const tr = el("tr");
      tr.appendChild(el("td", {}, mid));
      tr.appendChild(el("td", {}, String(v.crashes)));
      tr.appendChild(el("td", {}, v.disabled_by_health
        ? el("span", { class:"status-bad" }, "DISABLED")
        : el("span", { class:"status-ok" }, "ok")));
      tr.appendChild(el("td", { class:"muted" }, v.last_error || ""));
      const act = el("td", {});
      act.appendChild(el("button", { class:"secondary", onclick: async () => {
        await api("/api/health/reset", { method:"POST",
          body: JSON.stringify({ id: mid }) });
        loadHealth();
      } }, "Reset"));
      tr.appendChild(act);
      tb.appendChild(tr);
    }
    tbl.appendChild(tb);
    sec.appendChild(tbl);
  } catch (e) {
    sec.innerHTML = "";
    sec.appendChild(el("p", { class:"status-bad" }, e.message));
  }
}

// ---- Repos ----
async function loadRepos() {
  const sec = document.getElementById("tab-repos");
  sec.innerHTML = "";
  const tbar = el("div", { class:"toolbar row" });
  const inp = el("input", { class:"url", placeholder:"https://example.com/repo.json" });
  tbar.appendChild(inp);
  tbar.appendChild(el("button", { class:"secondary", onclick: async () => {
    if (!inp.value) return;
    await api("/api/repos/add", { method:"POST", body: JSON.stringify({ url: inp.value }) });
    inp.value = ""; loadRepos();
  } }, "Add"));
  tbar.appendChild(el("button", { class:"secondary", onclick: async () => {
    try {
      const r = await api("/api/update/check");
      toast("Updates: " + (r.available.length || 0));
    } catch (e) { toast(e.message, true); }
  } }, "Check for updates"));
  sec.appendChild(tbar);
  const data = await api("/api/repos");
  if (!data.urls.length) {
    sec.appendChild(el("p", { class:"muted" }, "No repos configured."));
    return;
  }
  for (const u of data.urls) {
    const row = el("div", { class:"mod row" });
    row.appendChild(el("div", { style:"flex:1" }, u));
    row.appendChild(el("button", { class:"bad", onclick: async () => {
      await api("/api/repos/remove", { method:"POST", body: JSON.stringify({ url: u }) });
      loadRepos();
    } }, "Remove"));
    sec.appendChild(row);
  }
}

// ---- Logs ----
let LOG_TIMER = null;
async function loadLog() {
  const sec = document.getElementById("tab-logs");
  sec.innerHTML = "";
  const tbar = el("div", { class:"toolbar row" });
  tbar.appendChild(el("button", { class:"secondary", onclick: async () => {
    await api("/api/log/clear", { method:"POST", body:"{}" });
    refresh();
  } }, "Clear"));
  const pre = el("pre", { class:"log" }, "");
  sec.appendChild(tbar);
  sec.appendChild(pre);
  async function refresh() {
    try {
      const r = await api("/api/log");
      pre.textContent = r.text || "(no log yet)";
      pre.scrollTop = pre.scrollHeight;
    } catch (e) { pre.textContent = e.message; }
  }
  await refresh();
  if (LOG_TIMER) clearInterval(LOG_TIMER);
  LOG_TIMER = setInterval(refresh, 2000);
}

loadMods();
</script>
</body>
</html>"""


def _render_html() -> bytes:
    return (HTML_TEMPLATE
            .replace("__CSRF__", CSRF_TOKEN)
            .replace("__API__", API_VERSION)
            .encode("utf-8"))


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class GuiHandler(BaseHTTPRequestHandler):
    server_version = "RSMM-GUI/1.0"

    # Quiet down the default access log.
    def log_message(self, fmt: str, *args) -> None:  # noqa: D401
        return

    def _send_json(self, code: int, body: dict | list) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, body: bytes, *, set_cookie: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if set_cookie:
            self.send_header(
                "Set-Cookie",
                f"rsmm_token={AUTH_TOKEN}; HttpOnly; SameSite=Strict; Path=/",
            )
        self.end_headers()
        self.wfile.write(body)

    def _gate(self, *, post: bool) -> bool:
        if not _check_host(self):
            self._send_json(400, {"error": "bad host"})
            return False
        if not _check_auth(self):
            self._send_json(401, {"error": "unauthorized"})
            return False
        if post and not _check_csrf(self):
            self._send_json(403, {"error": "csrf"})
            return False
        return True

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return {}

    # ---- GET --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/":
            # Authenticated via ?token=... on the first hit; then cookie.
            if not _check_host(self):
                self._send_json(400, {"error": "bad host"}); return
            if not _check_auth(self):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"unauthorized")
                return
            self._send_html(_render_html(), set_cookie=True)
            return
        if not self._gate(post=False):
            return
        if path == "/api/mods":
            return self._send_json(200, {"mods": _read_mods()})
        if path == "/api/health":
            return self._send_json(200, _health_snapshot())
        if path == "/api/repos":
            return self._send_json(200, {"urls": _load_repos()})
        if path == "/api/update/check":
            return self._send_json(200, _update_check())
        if path == "/api/log":
            return self._send_json(200, _read_log())
        self._send_json(404, {"error": "not found"})

    # ---- POST -------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if not self._gate(post=True):
            return
        body = self._read_body()
        if path == "/api/mod/toggle":
            ok = _set_enabled(str(body.get("id", "")), bool(body.get("enabled", True)))
            return self._send_json(200, {"ok": ok})
        if path == "/api/mod/config":
            return self._send_json(200, _set_config(body))
        if path == "/api/apply":
            return self._send_json(200, _run_apply())
        if path == "/api/health/reset":
            mid = str(body.get("id", ""))
            game = find_game_dir()
            if not game:
                return self._send_json(500, {"error": "no game dir"})
            Health(game / COOKING_SUBDIR).re_enable(mid)
            return self._send_json(200, {"ok": True})
        if path == "/api/health/clear":
            game = find_game_dir()
            if not game:
                return self._send_json(500, {"error": "no game dir"})
            h = Health(game / COOKING_SUBDIR)
            st = h.load()
            for mid in list(st.mods):
                h.re_enable(mid)
            h.clear_canary()
            return self._send_json(200, {"ok": True})
        if path == "/api/health/bisect":
            from rsmm.cli.safe_mode import _bisect_step
            game = find_game_dir()
            if not game:
                return self._send_json(500, {"error": "no game dir"})
            rc = _bisect_step(Health(game / COOKING_SUBDIR))
            return self._send_json(200, {"ok": rc == 0})
        if path == "/api/repos/add":
            url = str(body.get("url", "")).strip()
            if not url:
                return self._send_json(400, {"error": "url required"})
            _save_repos(sorted(set(_load_repos() + [url])))
            return self._send_json(200, {"ok": True})
        if path == "/api/repos/remove":
            url = str(body.get("url", ""))
            _save_repos([u for u in _load_repos() if u != url])
            return self._send_json(200, {"ok": True})
        if path == "/api/log/clear":
            return self._send_json(200, _clear_log())
        self._send_json(404, {"error": "not found"})


# ---------------------------------------------------------------------------
# Endpoint helpers
# ---------------------------------------------------------------------------


def _set_config(body: dict) -> dict:
    mid = str(body.get("id", ""))
    key = str(body.get("key", ""))
    val = body.get("value")
    mod_dir = MODS_DIR / mid
    if not mod_dir.is_dir():
        return {"error": "unknown mod"}
    try:
        ConfigStore(mod_dir).set(key, val)
    except ConfigError as e:
        return {"error": str(e)}
    return {"ok": True}


def _health_snapshot() -> dict:
    game = find_game_dir()
    out: dict[str, Any] = {"mods": {}, "canary": None, "game_build": ""}
    if not game:
        return out
    cooking = game / COOKING_SUBDIR
    if not cooking.is_dir():
        return out
    h = Health(cooking)
    st = h.load()
    out["mods"] = {mid: {
        "crashes": m.crashes,
        "last_error": m.last_error,
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


def _run_apply() -> dict:
    """Re-enter the applier in-process so we don't fork a python."""
    try:
        from rsmm.cli import apply_mods
        rc = apply_mods.main()
    except SystemExit as e:
        rc = e.code or 0
    except Exception as e:
        return {"ok": False, "message": str(e)}
    return {"ok": rc == 0, "message": f"exit {rc}"}


def _load_repos() -> list[str]:
    p = Path.home() / ".rsmm" / "repos.json"
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text(encoding="utf-8")).get("urls", []))
    except Exception:
        return []


def _save_repos(urls: list[str]) -> None:
    p = Path.home() / ".rsmm" / "repos.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"urls": urls}, indent=2), encoding="utf-8")


def _update_check() -> dict:
    """Re-use the CLI's planner; never downloads."""
    try:
        from rsmm.cli import update_cmd
    except Exception as e:
        return {"error": str(e), "available": []}
    repos = _load_repos()
    installed = update_cmd._installed_mods()
    if not repos or not installed:
        return {"available": []}
    avail: list[dict[str, Any]] = []
    for url in repos:
        try:
            raw = json.loads(update_cmd._fetch(url).decode("utf-8"))
            from rsmm.sdk.repo import RepoIndex
            idx = RepoIndex.load(raw)
        except Exception:
            continue
        for mid, have in installed.items():
            e = idx.find(mid)
            if e and update_cmd._newer(have, e.version):
                avail.append({"id": mid, "have": have, "want": e.version, "url": e.url})
    return {"available": avail}


def _log_path() -> Path:
    game = find_game_dir()
    if not game:
        return Path("/tmp/rsmm_log_missing")
    return game / "mods" / "_log.txt"


def _read_log() -> dict:
    p = _log_path()
    if not p.exists():
        return {"text": ""}
    try:
        # Cap at last 8000 lines so the browser doesn't choke on a big log.
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"text": "\n".join(lines[-8000:])}
    except Exception as e:
        return {"text": f"(read error: {e})"}


def _clear_log() -> dict:
    p = _log_path()
    if p.exists():
        try:
            p.write_text("", encoding="utf-8")
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True}


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Pick a random free port on localhost."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(port: int, *, open_browser: bool = True) -> None:
    """Start the GUI server (blocking). Press Ctrl+C to stop."""
    ALLOWED_HOSTS.update({f"127.0.0.1:{port}", f"localhost:{port}"})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), GuiHandler)
    url = f"http://127.0.0.1:{port}/?token={AUTH_TOKEN}"
    print(f"\nRSMM GUI running at:\n  {url}\n")
    print("Token kept in cookie after first hit; do not share this URL.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rsmm gui",
        description="Local web GUI for non-CLI users.")
    ap.add_argument("--port", type=int, default=0,
                    help="port to bind on 127.0.0.1 (default: random free port)")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't open the default browser")
    args = ap.parse_args(argv)
    port = args.port or _free_port()
    serve(port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
