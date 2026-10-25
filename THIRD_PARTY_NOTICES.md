# Third-Party Notices

Ravenswatch Mod Manager (RSMM) is MIT licensed (see [LICENSE](LICENSE)). This
file credits the work of others that RSMM ships or is built with, grouped by
the artifact it ends up in.

- **Loader DLL** (`dist/winhttp.dll`): statically links the libraries below;
  their license texts are reproduced in full.
- **Desktop app** (Tauri): bundles fonts and open-source frameworks, listed
  with their licenses.
- **CLI sidecar** (PyInstaller build of `src/rsmm/`): bundles the Python
  runtime. The Python code itself has no third-party runtime dependencies.

---

## Artwork

The RSMM logo and app icon are by **Arch**.

---

# Loader DLL

License copies are bundled in-tree under `src/loader/third_party/<lib>/`.
`Vulkan-Headers/` is also vendored there, but is not compiled into the
current loader (the in-game ImGui overlays were removed).

---

## MinHook — BSD-2-Clause

Source: `src/loader/third_party/minhook/LICENSE.txt`

```
MinHook - The Minimalistic API Hooking Library for x64/x86
Copyright (C) 2009-2017 Tsuda Kageyu.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

 1. Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.
 2. Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in the
    documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER
OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Portions also Copyright (c) 2008-2009, Vyacheslav Patkov
(Hacker Disassembler Engine 32/64 C), same BSD-2 terms.
```

---

## Lua 5.4 — MIT

Source: https://www.lua.org/license.html (Lua does not ship a LICENSE
file inside its source tree; the canonical text is published on lua.org
and is reproduced verbatim below).

```
Copyright © 1994–2024 Lua.org, PUC-Rio.

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## nlohmann/json 3.12.0 — MIT

Source: `src/loader/third_party/nlohmann/json.hpp` (header-only;
SPDX-License-Identifier: MIT)

```
MIT License

Copyright (c) 2013-2025 Niels Lohmann <https://nlohmann.me>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## toml++ 3.4.0 — MIT

Source: `src/loader/third_party/tomlplusplus/toml.hpp` (header-only;
SPDX-License-Identifier: MIT)

```
MIT License

Copyright (c) Mark Gillard <mark.gillard@outlook.com.au>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

# Desktop app

## Fonts — SIL Open Font License 1.1

Bundled through the `@fontsource` packages, so the app never fetches fonts at
runtime. Licensed under the [SIL Open Font License, Version 1.1](https://openfontlicense.org).

| Font | Copyright |
|------|-----------|
| Alegreya | Copyright 2011 The Alegreya Project Authors (https://github.com/huertatipografica/Alegreya) |
| Alegreya Sans | Copyright 2013 The Alegreya Sans Project Authors (https://github.com/huertatipografica/Alegreya-Sans) |
| JetBrains Mono | Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono) |

The website (`rsmm.me`) additionally serves UnifrakturCook (OFL 1.1) through
`next/font`.

## Frameworks and libraries

Direct dependencies of `apps/desktop`. Each package's full license text ships
inside the package itself.

| Component | License |
|-----------|---------|
| [Tauri](https://tauri.app) 2 and its plugins (shell, opener, deep-link, os, http, process, updater, global-shortcut, single-instance) | MIT OR Apache-2.0 |
| [React](https://react.dev) / React DOM | MIT |
| [TanStack Query](https://tanstack.com/query) / [TanStack Router](https://tanstack.com/router) | MIT |
| [Zustand](https://github.com/pmndrs/zustand) | MIT |
| [Lucide](https://lucide.dev) icons (`lucide-react`) | ISC |
| [Better Auth](https://better-auth.com) / `@daveyplate/better-auth-tauri` | MIT |
| [react-markdown](https://github.com/remarkjs/react-markdown) / [remark-gfm](https://github.com/remarkjs/remark-gfm) | MIT |
| [serde](https://serde.rs) / serde_json | MIT OR Apache-2.0 |

The full transitive lists can be produced with `pnpm licenses list` (in
`apps/desktop`) and `cargo tree` / `cargo about` (in `apps/desktop/src-tauri`).

---

# CLI sidecar

| Component | License |
|-----------|---------|
| [CPython](https://www.python.org) runtime and standard library | [PSF License Agreement](https://docs.python.org/3/license.html) |
| [PyInstaller](https://pyinstaller.org) bootloader | GPL-2.0 with the PyInstaller bootloader exception, which permits bundling it with software under any license |
