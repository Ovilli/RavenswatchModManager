---
title: Your first mod
description: Scaffold and ship a mod in five minutes.
---

```sh
./rsmm new MyMod
# edit mods/MyMod/manifest.toml + drop assets under mods/MyMod/assets/
./rsmm apply
./rsmm pack MyMod   # produces dist/MyMod.zip
```

Upload `dist/MyMod.zip` via the Registry tab in the desktop app to publish.
