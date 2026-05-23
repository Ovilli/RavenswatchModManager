# GhidraMCP — interactive RE via MCP

LaurieWired's GhidraMCP exposes the live Ghidra session over HTTP and
bridges it to MCP. Claude Code (or any MCP client) can then
`decompile_function`, `list_methods`, `rename_function`, etc. against
the already-analyzed `Ravenswatch.exe` without re-running headless
scripts.

This is complementary to the headless pipeline in [PIPELINE.md](PIPELINE.md):

- **Headless / `out/`** — bulk, batch, regenerated after game patch.
- **GhidraMCP** — live, iterative; great for "what calls this?" or
  "rename these 12 functions before the next dump".

## Inputs

```
~/Documents/Programming/ghidra_11.3_PUBLIC/      Ghidra install (v11.3)
~/.var/app/.../Ravenswatch/Ravenswatch.exe       target binary
./ghidra_project/Ravenswatch.rep/                pre-analyzed project
```

## One-time install

1. **Extension** — already installed at:
   `~/Documents/Programming/ghidra_11.3_PUBLIC/Ghidra/Extensions/GhidraMCP/`
   (`extension.properties` patched to `ghidraVersion=11.3` because the
   upstream release ships as 11.3.2.)

2. **Bridge** — `tools/ghidra_mcp/bridge_mcp_ghidra.py`. PEP-723 inline
   metadata declares `requests` + `mcp`; `uv run --script` resolves
   them on first run.

3. **MCP registration** — `.mcp.json` at repo root registers the
   `ghidra` server with stdio transport pointing at
   `http://127.0.0.1:8080/` (the embedded HTTP server inside Ghidra).

## Running

1. **Start Ghidra GUI**:

   ```
   ~/Documents/Programming/ghidra_11.3_PUBLIC/ghidraRun
   ```

2. **Enable the plugin** — `File → Configure → Miscellaneous`, check
   `GhidraMCPPlugin`. (First launch after install only.)

3. **Open the project + program** — `File → Open Project`,
   pick `./ghidra_project/Ravenswatch.gpr`, then double-click
   `Ravenswatch` in the project window so a CodeBrowser tool opens
   with the program. The HTTP server only serves the *currently open*
   program.

4. **Verify the server** — should be listening on
   `127.0.0.1:8080`:

   ```bash
   curl -s http://127.0.0.1:8080/methods | head
   ```

5. **Reload MCP in Claude Code** — `.mcp.json` is picked up on
   session start; `/mcp` lists the `ghidra` server.

## Available MCP tools

`list_methods`, `list_classes`, `list_segments`, `list_imports`,
`list_exports`, `list_namespaces`, `list_data_items`, `list_functions`,
`search_functions_by_name`, `decompile_function`,
`decompile_function_by_address`, `disassemble_function`,
`get_function_by_address`, `get_current_address`, `get_current_function`,
`rename_function`, `rename_data`, `rename_variable`.

Renames flow straight into the live Ghidra database — they persist
when you save the project, so iterative naming work survives across
sessions.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `curl: (7) Failed to connect` to `:8080` | No program open in CodeBrowser, or plugin not enabled. Open `Ravenswatch` in CodeBrowser. |
| `/mcp` shows `ghidra: failed` | Bridge couldn't reach `:8080`. Start Ghidra first, then restart Claude Code. |
| Ghidra refuses to load extension | Version mismatch in `extension.properties` — patch `ghidraVersion=` to match installed Ghidra. |
| Renames don't stick | Save project (`Ctrl+S` in CodeBrowser) before closing. |
