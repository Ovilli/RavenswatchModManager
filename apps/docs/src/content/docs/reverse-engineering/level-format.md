---
title: Level format and build path
description: The four layers of a cooked level, the gate that decides whether its objects are ever instantiated, and what an empty tile does and does not prove.
---

A tile's level is the file that says *what stands where*. Editing one is how a
mod adds a structure to the world, and it is the part of the pipeline where a
mistake is hardest to see: a malformed level parses, round-trips, passes every
cache and reference check, and produces a tile that is placed, built, and
completely empty. Nothing logs and nothing crashes.

This page is the map of that file and of the code that consumes it.

## A level is four nested layers

`<Biome>\Tiles\<Name>.level.ot` cooks to a `.GameStream.gen`, and an edit has to
be legal at every layer. Traced from `LevelStream_LoadStep` downward:

1. **The outer cooked container.** Type B, declaring class `oCGameStream`
   (id `0x14c31bf`, version 1.1). Sections are `MARK_BEGIN`/`MARK_END`
   delimited. `rsmm.engine.cooked` parses and re-emits it.
2. **`BufferLen`, and it is load-bearing.** `oCGameStream::Deserialize` reads a
   `u32` the engine itself names `BufferLen`, resizes a buffer to it, and then
   reads exactly that many raw bytes. **Everything past it is never seen.** That
   field is the `u32` pair at section-payload `+0x08`/`+0x0c`, equal to
   `len(payload) - 16`, which `cooked_schemas.asset_refs._restamp_self_size`
   maintains. It is not a corpus convention — it is the number the engine reads.
3. **A second cooked container fills that buffer.** Type A, `"Cooked"` magic,
   starting at payload `+0x10`. Its class table declares only
   `oCGameLevelIdentifier` (id `0x6494652`, version 1.3) and `oISerializable`,
   so every sub-object in a level is a level identifier plus a transform blob.
   Sections here carry **no length fields** — the reader scans for the balanced
   end marker — so an insert needs balanced markers and nothing else.
4. **The identifier itself.** `oCGameLevelIdentifier::Deserialize` reads four
   fields, gated on class version 1, 2 and 3. Shipped files are 1.3, so all four
   are read, and a clone must carry the class table through untouched.

### What a placement record contains

Records of one size within a level are byte-identical except for the transform.
Measured across a donor's 29 same-size records, the only varying bytes are
position, rotation and scale. **There is no per-object identity field**, so a
record copied as a template cannot collide with the one it came from, and the
level's own identity GUID is not back-referenced by its objects — it appears
exactly once in the file.

## The build path, and the gate

One function builds a level, and it is four calls:

```text
ResourceRef_Resolve            resolve the level resource
LevelStream_LoadStep(...)      false -> destroy the level, bail
gate(db, level, 0)             false -> destroy the level, null the slot
                               true  -> keep it, and instantiate its objects
```

`db` is the runtime `oCGameLevelDatabase` (class id `0x064a9acd`). **No shipped
asset declares it** — it is runtime-only, so there is no registry file a mod can
add itself to.

Inside the gate, after appending the level to the database's vector, a loop
walks the level's objects and calls a load-or-create for each. Three things can
leave a level empty, and all three are silent:

| Path | What happens |
| --- | --- |
| The accept check refuses | the loop never runs at all |
| The object count is zero | there is nothing to walk |
| Each object fails a mask test | they are skipped one by one |

:::caution[The skip test is a zero check, not a comparison]
The engine's `test` / `jbe` pair looks like a magnitude comparison. `test`
always clears the carry flag, so that `jbe` is really `je`: an object is skipped
precisely when the AND comes out **zero**. The array stride is the size of a
resource reference block, which puts the tested field exactly where a resolved
pointer lives — so this may be "skip every object whose resource never
resolved", the documented null-preload failure seen from the skip side rather
than the crash side.
:::

The symbols are in the map as `LevelDatabase_BuildAndRegister` and
`LevelObject_LoadOrCreate`; see [Engine symbols](/reference/symbols/). Both were
promoted only after the module's exception table confirmed each is a genuine
function start, which is the rule for any hook target.

## What an "incomplete" level load does not mean

`LevelStream_LoadStep` returns false in exactly two cases: the progress tick
says stop, or a state field is not 1. The tick is a **frame budget**, so a step
that has not finished is ordinarily a deferral and the loader is called again
next frame.

A trace of these fired once per placed mod tile across six playtests and was
recorded as a contradiction every time. It was the frame budget. Read the
resource names, never the count.

## Reading the evidence

Two habits cost more playtests in this area than every genuine bug combined.

### Pick probes by corpus exclusivity

A resolve count only means something if the name can only have come from the
thing you are testing. In one Dark Hills map:

| Probe | Shipped levels in the chapter that place it |
| --- | --- |
| A grass patch | 24 |
| A pike | 4 |
| A broken log | 3 |
| The bonfire | **0** — its only tile is in another chapter |

Four runs were spent on the first three, measuring vanilla traffic and
concluding nothing. Counting how many shipped levels place a name is one loop
over the uncooked corpus, and it is the difference between a measurement and a
number. Do it before reading any count.

### Decide whether a field is an input or an output

The gate fills `level+0xc8` and `level+0xc0` while it runs. A probe that read
them *before* the call reported zero objects for every level in the game, and
that was twice mistaken for a wrong offset. The offsets were right; the fields
are empty on entry.

Before reading a struct field around a call, decide whether that call *consumes*
the field or *produces* it, and read on the matching side. Read an output after,
and only when the call succeeded — on a failure the engine here destroys the
level, so anything read then is freed memory.

### A number that is wrong everywhere is a broken instrument

If a probe reports zero for levels that visibly build, the probe is wrong, not
the game — either the offset, or the moment, as above. Sanity-check every new
measurement against a case you know works *before* reading anything into the
case you are investigating. Where you can, prefer measurements that depend on no
struct offset at all, such as counting calls or resource fetches across a
window; they survive both mistakes.

Two more instrument traps, both of which produced confident wrong answers here:

- **A log budget can hide the one line that matters.** A cap of 40 met a map
  that builds exactly 40 levels, so the mod's own level was never printed and
  the run read as "our level never reaches the gate".
- **A trace that reads the wrong string field says nothing, loudly.** The
  resource trace printed the resource *root* for its whole life, so every line
  read `shaders` or `3D` and its name filter had never once been seen working.
  "Resolved zero times" and "the read is broken" were indistinguishable.

Both are fixed, and they are why the findings here cite what was measured rather
than what was inferred.

## Additive levels

A mod can own a level and place its own entity in it. `poi` supports this with
`own_level = true` plus a `places` entry naming `@prop`, which stands the entity
the def emits at a transform the def chooses. Nothing shipped is modified: no
entity is overwritten, no vanilla object is destroyed to borrow its slot, and
the marker's icon is cooked under a name the mod owns rather than repainted over
a shipped texture. A clean apply of such a mod creates **no backups**, which is
the check that it is genuinely additive.

The contrast is `swaps`, which re-dresses a slot the level author chose and
**inherits that slot's transform whole** — position, rotation and scale. That
single fact produced, in order: props tipped over, props buried below ground,
and a structure wedged inside a boulder. Prefer `places`.

:::note[Status]
A mod-owned level is placed, its resource resolves, and the gate keeps it. As of
this writing, whether its objects are instantiated is still open, and it is the
last unknown in the additive route. The three paths above are the whole
remaining hypothesis space.
:::
