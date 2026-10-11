---
title: Frequently asked questions
description: Short answers about safety, co-op, Steam Deck, saves, game updates and making mods.
sidebar:
  label: FAQ
---

## Using mods

### Is RSMM free?

Yes. RSMM is free and open source under the MIT licence. All of its code is on
[GitHub](https://github.com/Ovilli/RavenswatchModManager).

### Is it safe? Windows warned me about it.

Windows shows **"Windows protected your PC"** for programs that haven't paid for
a code-signing certificate, which is common for small free projects. Click
**More info**, then **Run anyway**. Download RSMM only from the official
[release page](https://github.com/Ovilli/RavenswatchModManager/releases/latest).

Mods on [rsmm.me](https://rsmm.me/registry) are scanned for malware before they
appear on the site. Mods you get anywhere else haven't been checked, so treat
them like any other download.

### Can I get banned for using mods?

RSMM doesn't change `Ravenswatch.exe` and doesn't try to get around anything that
protects the game. Most mods only swap data files on your own computer, like
pictures, numbers and text. Online, be considerate: don't bring mods that change
gameplay into strangers' games.

### Can I play co-op with mods?

It depends on the mod.

- **Mods that only change what *you* see or hear**, such as new looks, sounds,
  translations, a damage meter or a camera tweak, are fine. Your friends don't
  need them.
- **Mods that change the game itself**, such as stronger items, new enemies or
  different rules, should be installed by **everyone** in the group. Otherwise
  the game can behave differently for each player.

A mod's description should say which kind it is. If you have the modding tools,
`rsmm modpack` lists your mods in those two groups.

### Does it work on Steam Deck? On Mac?

**Steam Deck:** yes, with the Linux AppImage. See
[Install the app](/getting-started/install/).
**Mac:** no, macOS isn't supported.

### Will mods break my save?

Mods change the game's files, not your save files. Your saves are in the `_Save`
folder inside the game folder. Mods that add brand-new things (new items, new
enemies) carry the most risk, so copy `_Save` somewhere safe before you try one of
those.

### How do I get the normal game back?

- **For one session:** press **Launch Vanilla** in the app.
- **For good:** in the app, open **Commands** and run **Restore originals**.
- **To be extra sure:** in Steam, right-click Ravenswatch → **Properties** →
  **Installed Files** → **Verify integrity of game files**.

When you play with **Launch Modded**, RSMM already puts the original files back
when you close the game.

### Ravenswatch updated and my mods stopped working.

A game update replaces game files, which switches your mods off. The app notices
and shows **Ravenswatch updated — your mods were disabled by the game update**.
Press **Repair**, then **Launch Modded** as usual.

If a mod still doesn't work after that, it may need an update from its author.
Check the **Library** for updates.

### What's the difference between "Apply" and "Launch Modded"?

- **Launch Modded** puts your mods in, starts the game, and takes them out again
  when you quit. This is what you want almost every time.
- **Apply mods** (on the **Commands** page) puts your mods in and **leaves them
  there**, so you can start the game from Steam with mods. Use **Restore
  originals** to take them out.

### Some mods say "experimental". What does that mean?

RSMM works by understanding the game's files, and some kinds of changes aren't
fully understood yet. An **experimental** mod may not work completely, and could
crash the game. They're safe to try, since RSMM can always restore the original
files, but expect rough edges.

### What does "script mod" or "Lua mod" mean?

Most mods are **data**: they swap pictures, numbers or text. A few also include a
small program written in a language called **Lua**, which can react to things
happening in the game, such as showing a damage meter. Script mods need the
**loader**, which the app installs for you. On Linux and Steam Deck they're
experimental and need
[one Steam setting](/getting-started/install/#script-mods-on-linux-and-steam-deck).

## Making mods

### Do I need to know how to code?

No. The [web editor](/guides/web-editor/) changes items, talents and abilities
by clicking, and most mods are a short text file called `manifest.toml`. Code
(Lua) is only needed for script mods. Start with
[Make your first mod](/getting-started/first-mod/).

### What can a mod change?

| Area | Examples |
| --- | --- |
| **Look and sound** | Textures, 3D models, audio |
| **Balance** | Hero and enemy stats, talent values, magical object values |
| **Text** | Any text in the game, including whole translations |
| **New content** | New magical objects. Enemies, maps, shops and rewards work but are still experimental. |
| **Scripted gameplay** | Lua scripts that run inside the game |

### Do I need the app to make mods?

No. You can make mods with the web editor or the [modding tools](/getting-started/modding-tools/)
alone. The app is the easiest way to *play* them, and to see your mod the way
players will.

### How do I share my mod?

Run `rsmm pack MyMod` to make a `.zip`, then upload it on
[rsmm.me/publish](https://rsmm.me/publish). See
[Share your mod](/getting-started/first-mod/#share-your-mod).

## Getting help

### Where can I ask for help?

Open an issue on [GitHub](https://github.com/Ovilli/RavenswatchModManager/issues).
Include your operating system, your RSMM version (**Settings → About**), and a
[shared log link](/getting-started/troubleshooting/#share-your-log). First, try
the [troubleshooting page](/getting-started/troubleshooting/): it covers the most
common problems.
