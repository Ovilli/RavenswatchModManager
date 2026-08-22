---
title: Build a mod with an AI assistant
description: How to point ChatGPT, Claude, or a coding agent at RSMM so it builds a mod that actually loads.
---

Ravenswatch ships no official mod support — no Workshop, no loader, no
documented file format. An assistant asked "write me a Ravenswatch mod" with
nothing else to go on will either refuse or invent a plausible-looking mod
format that the game will never load. This page is how to give it the real one.

## The short version

Paste this at the start of the conversation:

```text
I'm modding Ravenswatch with the Ravenswatch Mod Manager (RSMM).
Read https://docs.rsmm.me/llms-mods.txt first — it is the complete
mod-authoring documentation in one file. Follow it exactly; do not
invent a mod format. Then help me build: <what you want>.
```

Any assistant that can fetch a URL will then be working from the real
manifest grammar, the real content kinds, and the real CLI.

## The machine-readable entry points

| URL | What it is | When to use it |
|-----|-----------|----------------|
| [`rsmm.me/llms.txt`](https://rsmm.me/llms.txt) | What RSMM is, and the shortest path from "I want a mod" to a working one | An assistant that has never heard of RSMM |
| [`docs.rsmm.me/llms-mods.txt`](https://docs.rsmm.me/llms-mods.txt) | Every authoring page, full text, one fetch | **Building a mod** |
| [`docs.rsmm.me/llms.txt`](https://docs.rsmm.me/llms.txt) | Link index of every docs page, grouped by section | Picking specific pages to read |
| [`docs.rsmm.me/llms-full.txt`](https://docs.rsmm.me/llms-full.txt) | The above plus ~30 pages of engine reverse-engineering notes | Working on RSMM itself |

Use `llms-mods.txt`, not `llms-full.txt`, to build a mod. The full corpus is
mostly vtable layouts and crash triage written for people extending RSMM's
engine support; feeding it to an assistant spends most of its context on
material it cannot act on, and dilutes the rules that matter.

## Rules an assistant gets wrong by default

These are the assumptions carried in from modding other games. State them
explicitly if your assistant starts drifting.

**A mod ships data, not code.** The deliverable is a `manifest.toml` with
`[[content]]` and `[[patch]]` blocks plus assets the SDK emits — never a Python
script that pokes at game files. `rsmm lint` fails any `*.py` in a mod that
isn't a sanctioned lifecycle hook, so a script-shaped answer doesn't just
violate convention, it fails CI. See [Mods ship data, not
code](/concepts/data-not-code/).

**Mod Lua never touches engine internals.** No literal game addresses, no
`_internal`, no `peek`/`poke`/`read_*`/`write_*`, no `engine.resolve`. Only the
high-level `R.*` API. Also lint-enforced. If the capability you want doesn't
exist in `R.*` yet, that's an RSMM change, not a mod change.

**Don't guess at content kinds.** The list of what can be modded is fixed and
each kind carries an honesty rating — `confirmed`, `experimental`, or `guess`.
Registering a kind rated below `confirmed` raises unless the mod opts in with
`sdk.Mod(..., experimental=True)`. An assistant will happily invent a kind name
that sounds right; `rsmm lint` will reject it. See [Content
kinds](/concepts/content-kinds/).

**Don't hand-edit the game folder.** Cooked asset paths under
`DarkTalesResources/_Cooking/` are ciphered, and RSMM tracks what it replaced
so it can roll back. Hand-edits there corrupt that state. Every change goes
through `rsmm apply` / `rsmm restore --all`.

## Verify what it produced

An assistant's mod is a hypothesis until the toolchain agrees. Three commands,
in order — each one catches a different class of wrong:

```sh
rsmm lint            # manifest grammar, asset paths, the rules above
rsmm apply           # install into the game (rsmm restore --all rolls it back)
rsmm pack <mod-id>   # zip it for the registry
```

`rsmm schema <kind>` lists the vanilla ids available to clone, which is the
single most common thing an assistant makes up. Run it and paste the output
back rather than letting it guess.

## Related

- [Your first mod](/getting-started/first-mod/) — the same loop, by hand.
- [Mod authoring guide](/guides/modding/) — scaffold through shipping.
- [CLI reference](/reference/cli/) — every command.
