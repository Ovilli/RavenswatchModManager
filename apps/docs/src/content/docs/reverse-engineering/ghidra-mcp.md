---
title: Ghidra MCP
description: Interactive reverse engineering of Ravenswatch through pyghidra-mcp.
---

[pyghidra-mcp](https://github.com/clearbluejar/pyghidra-mcp) serves the
already-analyzed Ghidra project over MCP, headless. Claude Code (or any MCP
client) can then decompile, search, cross-reference and rename against
`Ravenswatch.exe` without a Ghidra window open and without re-running
headless scripts.

This is complementary to the headless pipeline in [PIPELINE.md](/reverse-engineering/pipeline/):

- **Headless / `out/`** — bulk, batch, regenerated after game patch.
- **pyghidra-mcp** — live, iterative; great for "what calls this?" or
  "rename these 12 functions before the next dump".

It replaced LaurieWired's GhidraMCP bridge on 2026-10-10. That one needed the
Ghidra GUI open with a plugin enabled and served only the program open in
CodeBrowser.

## Inputs

```
~/Documents/Programming/ghidra_12.1.4_PUBLIC/    Ghidra install (>= 12.0 required)
./ghidra_project/Ravenswatch-New.gpr             pre-analyzed project
```

pyghidra refuses Ghidra 11.x. Opening the project in Ghidra 12 upgrades it,
and 11.x cannot open it afterwards — back the project up first (outside the
repo; `ghidra_project/` is gitignored, a copy elsewhere in the tree is not).

## Running

1. **Start the server** and leave it running:

   ```bash
   ./tools/ghidra_mcp/serve.sh
   ```

   It listens on `http://127.0.0.1:8765/mcp` (`RSMM_GHIDRA_MCP_PORT` changes
   the port, `GHIDRA_INSTALL_DIR` the Ghidra install). It opens the project
   without re-analyzing it; the first start also builds a search index of
   the decompiled code in the background, saved beside the project in
   `Ravenswatch-New-pyghidra-mcp/`, so later starts reuse it. Ctrl+C saves and
   closes the project.

2. **Connect** — `.mcp.json` (Claude Code) and `opencode.json` register the
   `ghidra` server at that URL. Start the server before the client session;
   `/mcp` should list `ghidra` as connected.

`./tools/ghidra_mcp/serve.sh --gui` launches the Ghidra GUI in the same
process, so renames and comments made over MCP show up in CodeBrowser
immediately. It cannot attach to a Ghidra you started yourself.

## Available MCP tools

- **Read:** `decompile_function` (by name or address, single or batch, with
  optional callees, strings and xrefs), `search_symbols_by_name` (regex),
  `search_code` (semantic or literal search over decompiled code),
  `search_strings`, `list_xrefs`, `gen_callgraph`, `read_bytes`,
  `list_imports`, `list_exports`.
- **Edit:** `rename_function`, `rename_variable`, `set_variable_type`,
  `set_function_prototype`, `set_comment`.
- **Project:** `list_project_binaries`, `list_project_binary_metadata`,
  `import_binary`, `delete_project_binary`.

Two gaps to know about: there is **no disassembly tool** (use
`scripts/disasm.py`), and **no way to define a function** at an address
Ghidra left undefined — that still needs a headless `analyzeHeadless`
postScript (run Ghidra 12's, since the project is now in its format).

## Terminal client

`pyghidra-mcp-cli` talks to the running server. Pin `mcp` to the server's
version — the client breaks against newer `mcp` releases:

```bash
uvx --with mcp==1.30.0 pyghidra-mcp-cli@0.2.7 --port 8765 \
  decompile --binary Ravenswatch.exe NamedEvent_Dispatch --callees --xrefs
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Ghidra version 11.3 is not supported` | Point `GHIDRA_INSTALL_DIR` at a Ghidra 12 install. |
| `/mcp` shows `ghidra: failed` | The server is not running. Start `serve.sh`, then reconnect. |
| Project is locked | Another Ghidra (GUI, headless, or a second `serve.sh`) has it open. Close that; delete `ghidra_project/*.lock*` only when no Ghidra process is running. |
| `search_code` returns nothing yet | The background index is still building; decompile and symbol search work meanwhile. |
| Ctrl+C does not stop `serve.sh` | While the first index is building it can ignore SIGINT for minutes. `kill -TERM` it; read-only lookups leave nothing unsaved, but save any renames first. |
| CLI: `not enough values to unpack` | The client picked up a newer `mcp`; pin it as shown above. |
