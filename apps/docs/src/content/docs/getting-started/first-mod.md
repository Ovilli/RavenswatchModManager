---
title: Your first mod
description: Install a mod from the Registry in under a minute.
---

Installing a mod with the desktop app takes just a few clicks.

## Using the desktop app

1. **Open** Ravenswatch Mod Manager
2. **Go to the Registry tab** — browse mods uploaded by the community
3. **Click a mod** to view its details, screenshots, and description
4. **Click Install** — the mod downloads and is added to your local collection
5. **Click Apply** — RSMM copies the mod's files into your Ravenswatch installation
6. **Launch the game** and enjoy

> To uninstall, open the Installed tab, find the mod, and click Uninstall. Then click Apply to revert the changes.

## Creating your own mod (advanced)

If you want to create and share your own mods, use the CLI:

```sh
# Create a new mod
./rsmm new MyMod

# The mod scaffold is created at mods/MyMod/manifest.toml
# Edit it to describe your mod, then drop files under mods/MyMod/assets/

# Apply your changes
./rsmm apply

# Package for sharing
./rsmm pack MyMod   # produces dist/MyMod.zip
```

Upload `dist/MyMod.zip` via the Registry tab in the desktop app to share it with the community.

## Next steps

- [CLI reference](/reference/cli/) — all available commands
- [Installation guide](/getting-started/install/) — desktop app and CLI setup
