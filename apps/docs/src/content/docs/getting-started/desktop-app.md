---
title: Using the app
description: Find mods, switch them on, play, and undo everything. A tour of every screen in the RSMM app.
sidebar:
  label: Using the app
---

This page walks you through the RSMM app: how to get a mod, play with it, and go
back to the normal game. If you haven't installed the app yet, start with
[Install the app](/getting-started/install/).

## The window at a glance

**Down the left side** are the app's pages:

| Page | What it's for |
| --- | --- |
| **Library** | The mods you have. Switch them on and off, change their settings, update them. |
| **Browse** | Every mod shared on [rsmm.me](https://rsmm.me/registry). Search and install from here. |
| **Profiles** | Saved sets of mods. Make a new one, switch between them, share one with a friend. |
| **Conflicts** | Only appears when two of your switched-on mods change the same thing. |
| **Commands** | Buttons for the less common jobs: health check, repair, restore the original game. |
| **Log** | What script mods wrote while the game was running. Useful when something breaks. |
| **Settings** | At the bottom. Game folder, language, look and feel, and the app's version. |

**Along the top** are the profile you're using and the two buttons you'll press
most:

- **Launch Modded** starts the game **with** your switched-on mods.
- **Launch Vanilla** starts the game **without** any mods.

Press **Ctrl+K** anywhere to open a search box that jumps to any page, mod or
action.

## Install a mod and play

1. Open **Browse**.
2. Find a mod you like. Use the search box, or the **Filters** for categories
   and ratings. Click a mod to read its description and see pictures.
3. Press **install**. The mod downloads and is added to your current profile,
   already switched on.

   Your very first install also creates a profile called **My Mods** and switches
   to it. That's because the **Default** profile is kept as the plain, unmodded
   game.
4. Press **Launch Modded** at the top.

That's it. The game starts with your mods.

### What Launch Modded actually does

1. It writes your switched-on mods into the game's files, keeping a copy of every
   original file first.
2. It starts Ravenswatch through Steam.
3. When you quit the game, it puts every original file back.

So the mods are only in the game **while you play from the app**. If you start
Ravenswatch straight from Steam, you get the normal game. If you want mods,
always start the game with **Launch Modded**.

:::note
Keep the RSMM app open while you play. It's what notices that the game closed
and cleans up afterwards.
:::

## Switch mods on and off

Every mod in the **Library** has a switch. Turn a mod off and it won't be used
the next time you press **Launch Modded**. The mod stays on your computer, so you
can turn it back on later.

- **Change how the list looks** with the three buttons at the top of the
  Library: cards, a compact list, or a view of every mod's settings at once.
- **Remove a mod for good** with its trash-can button. This deletes it from your
  computer.
- **Some mods need other mods** to work. If one is missing, the mod shows a red
  *missing deps* tag. Install the mods it names from **Browse**.

## Change a mod's settings

Some mods have options, like how strong an effect is or which items to ban.
Those mods have a **settings** button on their card (an icon of sliders).

1. Open the mod's settings and change what you like.
2. Press **Save**.
3. The change takes effect the next time you start the game. If the game is
   already running, quit it completely and press **Launch Modded** again.

## Keep your mods up to date

When a newer version of a mod you have comes out, the **Library** shows an
updates box at the top. Press **Update** next to one mod, or **Update all**. A
number next to **Library** in the sidebar tells you how many updates are
waiting.

## Profiles

A **profile** is a saved set of mods. For example, you could keep:

- **My Mods** for your everyday setup,
- **Silly Run** with chaos mods for playing with friends,
- **Default** for the plain game. Default can never hold mods.

On the **Profiles** page you can:

- **New profile**: start an empty one.
- **Activate**: switch to a profile. The Library then shows that profile's mods.
- **Duplicate**: copy a profile, mods included, to try changes without losing
  the original.
- **Export**: copy a short code you can send to a friend. They paste it under
  **Import** to get the same mod list.
- **Backup**: save or restore every profile and setting at once.
- **Open folder**: open the folder on your computer where that profile's mods
  are stored.

You can also switch profiles quickly from the name at the top left of the
window.

## Add a mod from a file

Got a mod as a `.zip` from a friend, or made one in the
[web editor](/guides/web-editor/)? Here's how to add it:

1. Unzip it. You should end up with a folder that has a `manifest.toml` file
   inside.
2. Open **Profiles**, find the profile you want (not Default), and press
   **Open folder**.
3. Move the mod's folder into the folder that opened.
4. Go to the **Library**. A banner says a mod is *on disk but not in this
   profile*. Press **Add to profile**.
5. Press **Launch Modded**.

## Conflicts

Sometimes two mods change the same part of the game, for example two mods that
both replace the same hero's look. Only one of them can win. When that happens:

- a red **conflicts** count appears at the top of the window,
- the **Conflicts** page appears in the sidebar and lists which mods clash.

Turn one of the clashing mods off, or leave it: the mod that loads **later** wins.

## Commands

The **Commands** page has buttons for jobs you won't need every day:

| Button | What it does |
| --- | --- |
| **Doctor** | Checks that the game, the mods and the loader are set up correctly. Run this first when something's wrong. |
| **Doctor + repair** | The same check, then fixes whatever it safely can. |
| **Apply mods** | Writes your mods into the game **without** starting it, and leaves them there. Useful if you want to start the game from Steam with mods. |
| **Restore originals** | Puts every original game file back and removes the loader. The "undo everything" button. |
| **Build** | Rebuilds generated mod files and applies them. Mostly for mod makers. |
| **Run vanilla** / **Run modded** | The same as the Launch buttons at the top. |

## Log

The **Log** page shows what script mods wrote while the game was running. Tick
**problems only** to see just errors and warnings. The drop-down lets you look at
earlier game sessions.

If a mod crashes the game three times in a row while it's starting up, RSMM skips
that mod on the next start and the Log page tells you which one. Press **Try
again** once you think it's fixed.

To ask someone for help, press **Share link**. It uploads the log and gives you a
link to paste into Discord or a GitHub issue. Read the preview first: personal
details like your user name are hidden, but anyone with the link can read it.
More in [Troubleshooting](/getting-started/troubleshooting/#share-your-log).

## Overlays

Some mods show a small window on top of the game, like a damage meter or a run
timer. Those mods have an **Overlay** button on their card. Press it to show the
window, and press it again to hide it.

- Drag the window by its top bar. Drag the **bottom-right corner** to resize it.
- **Compact** hides the footer.
- **Click-through** lets your clicks go through to the game. Press
  **Ctrl+Alt+O** to turn it off again, since you can't click a window that lets
  clicks through.
- Lost the window off-screen? **Shift-click** the Overlay button to put it back
  in the middle.
- Overlays can only sit on top of the game if Ravenswatch runs in **borderless
  windowed** mode, not exclusive fullscreen.

## Settings

| Tab | What's in it |
| --- | --- |
| **General** | Where the game is installed (**Game install**), where your mods are kept (**Mods folder**), mod sources and app updates. |
| **Appearance** | Language, font, text size, spacing and animations. |
| **Game** | Online server, loader features, and **Disable GPU acceleration** if the app draws badly or crashes your graphics driver. |
| **Diagnostics** | The app's own log and crash reports. |
| **About** | The app's version, release notes and credits. |

### Language

**Settings → Appearance → Language** switches the app between English and
简体中文 (Simplified Chinese). It changes right away, no restart needed. On first
start the app picks Chinese if your computer is set to Chinese, otherwise English.

Some text always stays in its original language: messages from the `rsmm`
command-line tool, text that mods write themselves, and the game's own text.

## Where your files are

| | Windows | Linux / Steam Deck |
| --- | --- | --- |
| Your mods | `%APPDATA%\rsmm\mods\profiles\<profile>\` | `~/.local/share/rsmm/mods/profiles/<profile>/` |
| Copies of the original game files | Next to each file in the game folder, with `.rsmm.bak` added to the name | Same |

You can move the mods folder under **Settings → General → Mods folder**. The quickest way to open a
profile's mods folder is the **Open folder** button on the **Profiles** page.

## Windows and Linux

The app works the same on both. The differences:

| | Windows | Linux / Steam Deck |
| --- | --- | --- |
| How it's installed | `x64-setup.exe` installer | AppImage, `.deb`, or the AUR |
| Mods that change looks, numbers, text | ✅ | ✅ |
| Script (Lua) mods | ✅ | Experimental, needs a [Steam launch option](/getting-started/install/#script-mods-on-linux-and-steam-deck) |
| Finding the game automatically | Every Steam library on every drive | Normal and Flatpak Steam, plus `/mnt` |

:::note[For translators]
A new app language is a file under `apps/desktop/src/locales/`. The
`coverage.test.ts` test fails the build if a translation is missing, unused, or
drops a `{placeholder}`.
:::
