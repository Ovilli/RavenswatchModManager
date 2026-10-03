"use strict";
// Shared by every editor page, inlined where the page names it when served.

// Replaced per launch. Every POST must echo it: it exists only in pages this
// server handed out, so another site open in the browser cannot write mods.
const TOKEN = "__RSMM_TOKEN__";

if (window.top !== window) document.documentElement.classList.add("embedded");

// GET `path`, or POST `body` as JSON. Resolves to the reply's JSON and throws
// its `error`. Paths are relative ("api/items"), so a page works at `/`, under
// a mount of `rsmm editor`, and in the web editor, where fetch is routed to
// the in-browser engine.
async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-RSMM-Token": TOKEN },
    body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({ error: "bad response (" + r.status + ")" }));
  if (!r.ok || data.error) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

// ---- the "New mod" form, shared by every editor that creates a mod ------------------
// The same questions wherever a mod is made, so a mod looks the same whichever tab
// started it. Resolves to `{id, meta}`, or null when cancelled; `error` reopens the
// form with the reason a first try was refused. The author is kept for next time
// (a per-viewer convenience: the page works the same without storage).
const AUTHOR_KEY = "rsmm.editor.author";
function askNewModDialog(modTags, error) {
  const g = (id) => document.getElementById(id);
  const dlg = g("newmoddlg"), tags = g("nm-tags");
  if (!tags.childElementCount) {
    for (const t of modTags || []) {
      const box = document.createElement("input"); box.type = "checkbox"; box.value = t;
      const label = document.createElement("label"); label.append(box, t); tags.append(label);
    }
  }
  if (!g("nm-author").value) {
    try { g("nm-author").value = JSON.parse(localStorage.getItem(AUTHOR_KEY) || '""') || ""; } catch { /* no storage */ }
  }
  g("nm-error").textContent = error || "";
  return new Promise(resolve => {
    dlg.onclose = () => {
      if (dlg.returnValue !== "ok") { resolve(null); return; }
      const picked = [...tags.querySelectorAll("input:checked")].map(i => i.value);
      const more = g("nm-moretags").value.split(",").map(t => t.trim()).filter(Boolean);
      const meta = {
        name: g("nm-name").value, author: g("nm-author").value, version: g("nm-version").value,
        summary: g("nm-summary").value, description: g("nm-desc").value, tags: [...picked, ...more],
        license: g("nm-license").value, homepage_url: g("nm-home").value, repo_url: g("nm-repo").value };
      if (meta.author.trim()) { try { localStorage.setItem(AUTHOR_KEY, JSON.stringify(meta.author.trim())); } catch { /* no storage */ } }
      resolve({ id: g("nm-id").value.trim(), meta });
    };
    dlg.returnValue = "";
    dlg.showModal();
    g("nm-id").focus();
  });
}
