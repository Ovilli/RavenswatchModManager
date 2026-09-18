"""Auto-generate the SDK/CLI reference from `@sdk_export` registrations.

Walks `rsmm.sdk.api.registry()`, pulls each function's signature +
docstring, and emits one Markdown file per submodule. Run via
`rsmm docs-gen`.

Two destinations, one source of truth:
- `out_dir` (default `docs/api/`) — plain Markdown, CI `--check`s it.
- `site_out` (default `apps/docs/src/content/docs/reference/sdk-api/`) —
  the same pages with Starlight frontmatter so they render on the docs site.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

from .api import registry


def _import_sdk_modules() -> None:
    """Side-effect import every `rsmm.sdk.*` so decorators fire."""
    import logging

    import rsmm.sdk as pkg
    for _, name, _ in pkgutil.walk_packages(pkg.__path__, prefix="rsmm.sdk."):
        try:
            importlib.import_module(name)
        except Exception as e:  # noqa: BLE001 — one bad module shouldn't abort the build
            logging.getLogger(__name__).warning(
                "docs-gen: skipped %s (import failed: %s)", name, e
            )


def _yaml_str(s: str) -> str:
    """Quote a frontmatter scalar if it contains YAML-significant chars."""
    if not s:
        return '""'
    if any(c in s for c in ':#"\'\n') or s[0] in "[{>|*&!%@`":
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _first_sentence(doc: str, limit: int = 160) -> str:
    """First sentence/line of a docstring, collapsed to one line for frontmatter."""
    text = " ".join(doc.strip().split())
    if not text:
        return ""
    # cut at first sentence end if it lands within the limit, else hard-truncate
    dot = text.find(". ")
    if 0 < dot < limit:
        return text[: dot + 1]
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _module_doc(mod_name: str) -> str:
    """Module-level docstring (full), or '' if none."""
    try:
        mod = importlib.import_module(mod_name)
    except Exception:  # noqa: BLE001
        return ""
    return (inspect.getdoc(mod) or "").strip()


def _write(out_dir: Path | None, site_out: Path | None, rel: str, text: str,
           title: str, description: str = "") -> list[Path]:
    """Write one page to whichever destinations are set. Returns paths written.

    Plain `out_dir` copies get the body verbatim; `site_out` copies are
    prefixed with Starlight frontmatter (title + optional description).
    """
    written: list[Path] = []
    if out_dir is not None:
        p = out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(p)
    if site_out is not None:
        p = site_out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        fm = f"---\ntitle: {_yaml_str(title)}\n"
        if description:
            fm += f"description: {_yaml_str(description)}\n"
        fm += "---\n\n"
        p.write_text(fm + text, encoding="utf-8")
        written.append(p)
    return written


def _render_member(name: str, fn) -> list[str]:
    """One member: fenced signature heading + docstring (or undocumented note)."""
    try:
        sig = str(inspect.signature(fn))
    except (TypeError, ValueError):
        sig = "(...)"
    doc = inspect.getdoc(fn)
    out = [f"### `{name}`", "", "```python", f"{name}{sig}", "```", ""]
    if doc:
        out += [doc, ""]
    else:
        out += [":::caution[Undocumented]", "No docstring yet — see the source.",
                ":::", ""]
    return out


def _module_page(mod_name: str, items: list[tuple[str, object]]) -> tuple[str, str]:
    """Return (body, description) for one SDK submodule page."""
    lines = [f"# {mod_name}", ""]
    mdoc = _module_doc(mod_name)
    description = _first_sentence(mdoc) if mdoc else f"SDK reference for {mod_name}."
    if mdoc:
        lines += [mdoc, ""]
    lines += [
        ":::note",
        "Auto-generated from `@sdk_export` registrations by `rsmm docs-gen`. "
        "Edit the docstrings in the source module, not this page.",
        ":::",
        "",
    ]

    # Group members by their leading `Class.` prefix; bare functions go last.
    groups: dict[str, list[tuple[str, object]]] = {}
    for name, fn in sorted(items):
        cls = name.split(".", 1)[0] if "." in name else ""
        groups.setdefault(cls, []).append((name, fn))

    for cls in sorted(groups, key=lambda c: (c == "", c)):
        members = groups[cls]
        if cls:
            lines += [f"## `{cls}`", ""]
        else:
            lines += ["## Functions", ""]
        for name, fn in members:
            lines += _render_member(name, fn)

    return "\n".join(lines).rstrip() + "\n", description


def _cli_page() -> tuple[str, str, str, str]:
    """Return (relpath, body, title, description) for the CLI inventory page."""
    from rsmm.cli._dispatch import iter_commands

    rows: list[tuple[str, str, str]] = []
    for cmd, modname in sorted(set(iter_commands())):
        try:
            mod = importlib.import_module(modname)
            doc = (inspect.getdoc(mod) or "").strip().splitlines()
            summary = doc[0] if doc else ""
        except Exception as e:  # noqa: BLE001 — report, don't crash docs build
            summary = f"(import failed: {e})"
        rows.append((cmd, modname, summary))

    lines = [
        "# rsmm CLI reference",
        "",
        "Every `rsmm` subcommand, auto-generated from the dispatch table "
        "(`rsmm.cli._dispatch.iter_commands`).",
        "",
        ":::note",
        "Do not edit by hand — run `rsmm docs-gen` after adding or renaming a "
        "subcommand. For task-oriented prose, see the "
        "[CLI guide](/reference/cli/).",
        ":::",
        "",
        f"**{len(rows)} commands.**",
        "",
        "| Command | Module | Summary |",
        "|---|---|---|",
    ]
    for cmd, modname, summary in rows:
        lines.append(f"| `rsmm {cmd}` | `{modname}` | {summary} |")
    body = "\n".join(lines) + "\n"
    return "cli.md", body, "CLI command inventory", "Every rsmm subcommand, auto-generated."


def _kinds_page() -> tuple[str, str, str, str]:
    """Return (relpath, body, title, description) for the content-kind table.

    Generated so the ratings cannot drift: `KIND_CONFIDENCE` is the single
    source of truth, and the row for each kind is built from it plus the
    builder module's own summary line. Prose pages link here instead of
    restating a rating that will be stale the next time one is proven.
    """
    from rsmm.sdk.content import _KIND_MODULES, KIND_CONFIDENCE, KINDS, _load_kind

    badge = {"confirmed": "✅ confirmed", "experimental": "⚠️ experimental",
             "guess": "❓ guess"}
    rows: list[tuple[str, str, str, str]] = []
    for kind in KINDS:
        rating = KIND_CONFIDENCE.get(kind, "guess")
        mod_name = _KIND_MODULES.get(kind, f"{kind}s")
        try:
            summary = (inspect.getdoc(_load_kind(kind)) or "").strip().splitlines()[0]
        except Exception as e:  # noqa: BLE001 — a broken builder shouldn't kill docs
            summary = f"(builder import failed: {e})"
        # The summary's own "— SDK entry point" tail says nothing here.
        for tail in (" — SDK entry point.", " — SDK entry point", " (SDK entry)."):
            if summary.endswith(tail):
                summary = summary[: -len(tail)] + "."
        rows.append((kind, badge.get(rating, rating), f"rsmm.sdk.kinds.{mod_name}", summary))

    counts = {r: sum(1 for k in KINDS if KIND_CONFIDENCE.get(k) == r)
              for r in ("confirmed", "experimental", "guess")}
    lines = [
        "# Content kinds & confidence",
        "",
        "Every content kind carries an honesty rating — how much the bytes it "
        "emits are trusted. This page is generated from "
        "`rsmm.sdk.content.KIND_CONFIDENCE`, which is what the SDK and "
        "`rsmm lint` actually enforce, so it cannot drift from the code.",
        "",
        ":::note",
        "Do not edit by hand, and do not restate a rating in prose — link here. "
        "Run `rsmm docs-gen` after changing a rating; CI `--check`s it.",
        ":::",
        "",
        f"**{len(KINDS)} kinds** — {counts['confirmed']} confirmed, "
        f"{counts['experimental']} experimental, {counts['guess']} guess.",
        "",
        "| Kind | Confidence | Builder | What it does |",
        "|---|---|---|---|",
    ]
    for kind, rating, mod_name, summary in rows:
        lines.append(f"| `{kind}` | {rating} | `{mod_name}` | {summary} |")
    lines += [
        "",
        "## What a rating means",
        "",
        "| Rating | Meaning | To ship it |",
        "|---|---|---|",
        "| ✅ `confirmed` | The emitted bytes were verified in-game, end to end. "
        "| Nothing extra. |",
        "| ⚠️ `experimental` | Codecs round-trip and the emit succeeds, but the "
        "in-game path is unproven. | `sdk.Mod(..., experimental=True)` / "
        "`experimental = true`. |",
        "| ❓ `guess` | The byte layout is an educated guess. May be rejected, "
        "may crash. | Same opt-in, plus your own testing. |",
        "",
        "A mod that registers any non-`confirmed` kind must opt in, and its "
        "manifest records it — so nobody ships speculative content believing it "
        "works. `rsmm lint` fails the mod otherwise.",
        "",
        "The *reason* behind each rating — what was proven, when, and what the "
        "rating is still waiting on — is written beside the rating in "
        "`src/rsmm/sdk/content.py`. Start there before changing one.",
        "",
        "## Starting one",
        "",
        "[First mod, by kind](/guides/first-mod-by-kind/) has a minimal, "
        "working `manifest.toml` for every row above.",
    ]
    return ("kinds.md", "\n".join(lines) + "\n", "Content kinds & confidence",
            "Per-kind honesty ratings, generated from KIND_CONFIDENCE.")


def _site_index(module_slugs: list[tuple[str, str]]) -> tuple[str, str]:
    """Landing page for the site's sdk-api section. Returns (body, description)."""
    from .api import API_VERSION

    lines = [
        "# SDK API reference",
        "",
        f"Generated reference for the `rsmm.sdk` Python API (API version "
        f"**{API_VERSION}**). One page per submodule, built from "
        "`@sdk_export` registrations.",
        "",
        ":::tip[New to the SDK?]",
        "Start with the [Authoring mods guide](/guides/modding/) and the "
        "[SDK design notes](/guides/sdk/). This section is the exhaustive "
        "symbol-level reference.",
        ":::",
        "",
        "## CLI",
        "",
        "- [CLI command inventory](/reference/sdk-api/cli/) — every `rsmm` subcommand.",
        "",
        "## Content kinds",
        "",
        "- [Content kinds & confidence](/reference/sdk-api/kinds/) — every kind, "
        "its rating, and its builder.",
        "",
        "## Modules",
        "",
    ]
    for slug, mod_name in module_slugs:
        lines.append(f"- [`{mod_name}`](/reference/sdk-api/{slug}/)")
    body = "\n".join(lines) + "\n"
    return body, "Generated symbol-level reference for the rsmm.sdk Python API."


def generate(out_dir: Path | None, site_out: Path | None = None) -> list[Path]:
    """Write one `<module>.md` per SDK submodule + `cli.md` + index pages.

    Writes to `out_dir` (plain) and/or `site_out` (with Starlight
    frontmatter). Returns every path written.
    """
    _import_sdk_modules()
    by_module: dict[str, list[tuple[str, object]]] = {}
    for name, fn in registry().items():
        mod = getattr(fn, "__module__", "rsmm.sdk")
        by_module.setdefault(mod, []).append((name, fn))

    written: list[Path] = []
    module_slugs: list[tuple[str, str]] = []
    for mod_name, items in sorted(by_module.items()):
        slug = mod_name.replace("rsmm.sdk.", "").replace(".", "_") or "root"
        module_slugs.append((slug, mod_name))
        body, description = _module_page(mod_name, items)
        written += _write(out_dir, site_out, f"{slug}.md", body, mod_name, description)

    # cli.md
    cli_rel, cli_body, cli_title, cli_desc = _cli_page()
    written += _write(out_dir, site_out, cli_rel, cli_body, cli_title, cli_desc)

    # kinds.md — the one place a kind's confidence is written down for readers.
    k_rel, k_body, k_title, k_desc = _kinds_page()
    written += _write(out_dir, site_out, k_rel, k_body, k_title, k_desc)

    # Site landing page (index.md) — site only; the repo copy uses README.md.
    site_body, site_desc = _site_index(module_slugs)
    written += _write(None, site_out, "index.md", site_body, "SDK API reference", site_desc)

    # README.md index — repo-side only; the docs site uses its sidebar + index.md
    # instead, so the relative `.md` links here never reach the link validator.
    idx_lines = ["# SDK v3 API reference", "",
                 "API version: see `rsmm.sdk.api.API_VERSION`", "",
                 "## CLI", "",
                 "- [cli](cli.md) — every `rsmm` subcommand", "",
                 "## Content kinds", "",
                 "- [kinds](kinds.md) — every kind and its confidence rating", "",
                 "## SDK modules", ""]
    for slug, _mod_name in module_slugs:
        idx_lines.append(f"- [{slug}]({slug}.md)")
    written += _write(out_dir, None, "README.md", "\n".join(idx_lines) + "\n",
                      "SDK API reference")
    return written
