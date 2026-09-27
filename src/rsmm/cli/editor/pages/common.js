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
