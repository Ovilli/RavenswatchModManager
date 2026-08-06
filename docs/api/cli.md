# rsmm CLI reference

Every `rsmm` subcommand, auto-generated from the dispatch table (`rsmm.cli._dispatch.iter_commands`).

:::note
Do not edit by hand — run `rsmm docs-gen` after adding or renaming a subcommand. For task-oriented prose, see the [CLI guide](/reference/cli/).
:::

**45 commands.**

| Command | Module | Summary |
|---|---|---|
| `rsmm apply` | `rsmm.cli.apply_mods` | Ravenswatch Mod Manager — install-time mod applier. |
| `rsmm build` | `rsmm.cli.build` | rsmm build — full pipeline. |
| `rsmm cmd` | `rsmm.cli.console_cmd` | rsmm cmd — send /commands to the in-game console runtime. |
| `rsmm collection` | `rsmm.cli.cmd_collection` | rsmm collection <subcommand> — manage mod collections. |
| `rsmm compat` | `rsmm.cli.compat` | Manifest compatibility graph. |
| `rsmm completion` | `rsmm.cli.cmd_completion` | rsmm completion — emit a shell tab-completion script. |
| `rsmm cook` | `rsmm.cli.cook` | rsmm cook — pack an editable source-format file into a cooked asset. |
| `rsmm decode` | `rsmm.engine.ot_decoder` | oCTextSaver binary decoder. |
| `rsmm disable` | `rsmm.cli.cmd_mods` | `rsmm enable` / `rsmm disable` — toggle mods from the terminal. |
| `rsmm docs-gen` | `rsmm.cli.docs_gen_cmd` | `rsmm docs-gen` — write the SDK/CLI reference from @sdk_export registrations. |
| `rsmm doctor` | `rsmm.cli.doctor` | rsmm doctor — system health check, and the repair path for what it finds. |
| `rsmm enable` | `rsmm.cli.cmd_mods` | `rsmm enable` / `rsmm disable` — toggle mods from the terminal. |
| `rsmm enemies` | `rsmm.cli.cmd_enemies` | `rsmm enemies` — discover vanilla enemies for enemy modding. |
| `rsmm home` | `rsmm.cli.cmd_shell` | Interactive home screen — what bare `./rsmm` opens in a terminal. |
| `rsmm install` | `rsmm.cli.cmd_install` | rsmm install — fetch, verify, and unpack a packed mod. |
| `rsmm install-loader` | `rsmm.cli.install_loader` | rsmm install-loader — copy winhttp.dll + SDK lib into the game install. |
| `rsmm intents` | `rsmm.cli.cmd_intents` | `rsmm intents` — consume in-game mod-menu intents written by the loader. |
| `rsmm items` | `rsmm.cli.cmd_items` | `rsmm items` — discover vanilla magical objects for item modding. |
| `rsmm json` | `rsmm.cli.json_bridge` | rsmm json — machine-readable bridge for the desktop / web UI. |
| `rsmm keygen` | `rsmm.cli.repo_cmd` | `rsmm repo`, `rsmm sign`, `rsmm verify`, `rsmm keygen`. |
| `rsmm lint` | `rsmm.cli.lint` | rsmm lint — per-mod manifest + assets validator. |
| `rsmm list` | `rsmm.cli.apply_mods` | Ravenswatch Mod Manager — install-time mod applier. |
| `rsmm log` | `rsmm.cli.cmd_log` | rsmm log — read the loader log from the game install directory. |
| `rsmm menu` | `rsmm.cli.cmd_menu` | `rsmm menu` — generate and inspect the in-game mod-list page (native book UI). |
| `rsmm merge` | `rsmm.cli.merge` | Patch-merge layer. |
| `rsmm new` | `rsmm.cli.cmd_new` | rsmm new — scaffold a mod directory. |
| `rsmm pack` | `rsmm.cli.cmd_pack` | rsmm pack — bundle a mod for distribution. |
| `rsmm rebuild-asset-map` | `rsmm.engine.find_iyg` | Ravenswatch Asset Decrypter — builds a full obfuscated -> plaintext |
| `rsmm repo` | `rsmm.cli.repo_cmd` | `rsmm repo`, `rsmm sign`, `rsmm verify`, `rsmm keygen`. |
| `rsmm restore` | `rsmm.cli.apply_mods` | Ravenswatch Mod Manager — install-time mod applier. |
| `rsmm run` | `rsmm.cli.run` | rsmm run — launch Ravenswatch via Steam, ensuring the WINEDLLOVERRIDES |
| `rsmm safe-mode` | `rsmm.cli.safe_mode` | `rsmm safe-mode` — drive the SDK health quarantine. |
| `rsmm save` | `rsmm.cli.cmd_save` | `rsmm save` — inspect Ravenswatch profile saves. |
| `rsmm schema` | `rsmm.cli.cmd_schema` | rsmm schema — list cloneable vanilla content ids. |
| `rsmm sdk-doctor` | `rsmm.cli.sdk_doctor` | `rsmm sdk-doctor` — SDK v3 self-check. |
| `rsmm sign` | `rsmm.cli.repo_cmd` | `rsmm repo`, `rsmm sign`, `rsmm verify`, `rsmm keygen`. |
| `rsmm symbols` | `rsmm.cli.cmd_symbols` | ``rsmm symbols`` — the engine symbol map (Minecraft-style mappings). |
| `rsmm talents` | `rsmm.cli.cmd_talents` | `rsmm talents` — discover + edit hero talent ("Skill") values. |
| `rsmm test` | `rsmm.cli.test` | rsmm test — diff a mod's patch plan against a checked-in fixture. |
| `rsmm uncook` | `rsmm.cli.uncook` | rsmm uncook — extract a cooked asset to an editable source-format file. |
| `rsmm unify` | `rsmm.cli.unify` | rsmm unify — assemble one Blender-loadable GLB per hero. |
| `rsmm update` | `rsmm.cli.update_cmd` | `rsmm update` — pull updates for installed mods from configured repos. |
| `rsmm update-data` | `rsmm.cli.cmd_update_data` | `rsmm update-data` — pull the latest pattern DB without an app release. |
| `rsmm verify` | `rsmm.cli.repo_cmd` | `rsmm repo`, `rsmm sign`, `rsmm verify`, `rsmm keygen`. |
| `rsmm watch` | `rsmm.cli.watch` | rsmm watch — live re-apply on mods/ change. |
