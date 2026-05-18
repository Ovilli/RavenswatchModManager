# Hook target candidates (feature → function map)

Distilled from a string-anchor sweep of `out/strings.json` and the
`out/decompiled_all/` corpus. Each row maps one of the community
feature requests to the most promising candidate function(s) for
`rsmm.hook` once the API ships.

Status legend:

- **anchor** — we have a string constant inside the function, so the
  function clearly *participates* in this subsystem; deeper RE
  needed to confirm whether to hook the function itself, its caller,
  or one of its callees.
- **registry** — function constructs the event-name table (or
  similar metadata); not itself a useful hookpoint, but its
  string-xrefs lead to the real dispatchers / consumers.
- **dispatcher** — function emits events of this type; hookable
  directly (intercept arg) or in chain (replace pre/post).
- **consumer** — function reacts to the event (likely the gameplay
  logic).

## Glossary

The game's internal vocabulary differs from the community's:

| Community word | Engine word           |
|----------------|-----------------------|
| Talent         | **Skill**             |
| Item           | **Magical Object** (MO) |
| Curse / Curse item | MO with `Cursed` tag |
| Refugee / Vendor   | **Refugee Archetype** (NPC archetype picker) |
| Aggro range        | not yet found — probably on `oCEnemyCampDifficultyDefinition` or similar |
| Difficulty/scaling | **Camp Difficulty Modifier** + `Difficulty Xp Modifier` |
| Talent stacking    | **Skill** add — currently dedup-guarded somewhere downstream of "Skill selected" |
| Talent restriction | **Skill** rolltable filter (in `Skill propose`) |

## Anchors found so far

| Feature                              | Anchor fn (link VA)     | Source string(s)                                                                 | Role |
|--------------------------------------|-------------------------|----------------------------------------------------------------------------------|------|
| Game event-name registry             | `FUN_1401d1850` (`0x1401d1850`) | `Skill propose`, `Skill selected`, `Level up`, `Pick Up Magical Object`, `Magical Object Destroyed`, `{Common,Rare,Epic,Legendary,Cursed} Magical Object Destroyed`, `Hero kill streak`, `Hero permadeath`, `Final victory never using any feather` | registry |
| Game-state machine (modifiers)       | `FUN_1401d6b10` (`0x1401d6b10`) | `Is in victory sequence`, `Is in defeat sequence`, `Difficulty Xp Modifier`, `Camp Difficulty Modifier`, `Camp Difficulty Modifier Chance To Apply`, `Half Cycle Count Before Boss Awakens Modifier` | dispatcher |
| Skill choice surface (`Extra skill` / `Extra MO`) | `FUN_1401d2e90` (`0x1401d2e90`) | `Extra skill choice`, `Extra MO Choice`                                          | dispatcher |
| GameOptions ctor (Forced seed lives here) | `FUN_1401c6d60` (`0x1401c6d60`) | `Forced seed`                                                                | registry — already used by `mods/ExampleSeedPin` |
| Run-end emitter                      | `FUN_1401f1a40` (`0x1401f1a40`) | `run_end`                                                                       | dispatcher |
| Run-level emitters                   | `FUN_1401f3b90`, `FUN_1401f2c80` | `level_reached`, `level_up_reach`                                              | dispatcher |
| Run-abandon emitter                  | `FUN_140291190`, `FUN_1402836a0`, `FUN_140292090` | `Abandon`                                                              | dispatcher (multiple call sites — narrow before hooking) |
| Resource lookup (already hooked Phase 3) | `FUN_140487040` (`0x140487040`) | n/a                                                                          | consumer — every cooked entity-by-path resolution |

## Feature → action plan

The "next RE step" column points at the concrete work needed before
each hook can be implemented. Most of them are short follow-ups on the
anchor function (a single Ghidra xref pass, or a 10-minute decomp
read).

### Talents

| User-requested feature                            | Anchor / candidate         | Next RE step                                                                                                   |
|---------------------------------------------------|---------------------------|----------------------------------------------------------------------------------------------------------------|
| Add talents (custom Lua-defined skill)            | Need: `Skill propose` consumer | Xref `"Skill propose"` from `FUN_1401d1850`; find the *emitter*; the row of three skills is built somewhere in that flow. |
| Restrict which talents can appear                 | Same as above             | Hook the skill-roll function; filter the candidate list before it's returned to UI.                            |
| Stack same talent multiple times                  | Find the dedup guard      | Xref `"Skill selected"` consumer; the function that records the chosen skill onto the hero almost certainly contains an `if (already_has(skill_id)) reject;` branch — patch / hook that. |
| Talent selection beyond lvl 10 (Heredos)          | `FUN_1401d2e90` (`Extra skill choice`) | Read decomp; find the `level >= 10` guard or the cap-counter increment; either bump the cap or insert hook to grant. |
| "Activate all talents" buff                       | Need: skill-effect dispatcher | Find the function that, on hero update, walks the hero's skill list and applies each — call it from a Lua tick with every skill id. |
| "Pick one talent" item                            | Need: `Skill propose` emitter | Same flow as restrict; replace candidate list with a single deterministic id. |
| Add extra talents at level 11 (curse / legendary) | `FUN_1401d2e90` + skill-grant | Combine: emit `Extra skill choice` on level 11 with a curse-tagged pool. |

### Magical Objects (items, curses, legendaries)

| Feature                                  | Anchor                       | Next step                                                                                                  |
|------------------------------------------|------------------------------|------------------------------------------------------------------------------------------------------------|
| Add new MO                               | Asset-side (entity def)      | Already partially supported via cooked-asset overrides; new entity needs the `.gen` re-encoder (separate track). |
| Modify MO (effects)                      | `FUN_1401d1850` events + the MO def | Live-modify via memory writes on the MO's modifier table. |
| Legendaries/cursed limited to 1          | Need: MO pool filter         | Xref `"Legendary Magical Object Destroyed"` / `"Cursed Magical Object Destroyed"` to find the picker; insert hook that rejects a second roll of the same rarity. |
| Extra MO choice (already exists as engine surface) | `FUN_1401d2e90` (`Extra MO Choice`) | Same function as `Extra skill choice` — confirm both go through one dispatcher. |

### Scaling / difficulty

| Feature                                | Anchor                       | Next step                                                                                                  |
|----------------------------------------|------------------------------|------------------------------------------------------------------------------------------------------------|
| Act 2 / Act 3 harder than baseline     | `FUN_1401d6b10` (`Camp Difficulty Modifier`, `Difficulty Xp Modifier`) | Read decomp; modifiers are floats. Two paths: (a) hook the modifier *getter* and multiply, (b) write the underlying float to `GlobalValues_Common/NGP_Enemy_*_Modifier.globalvalue` cooked file. Path (b) ships today; (a) needs hooks. |
| 4-player density (XP / HP / stagger scaled) | Same                         | The same modifier struct includes XP. Hook the player-count → modifier-product function; bump density independently of player count. |
| Movement speed / attack speed / cooldown / aggro range (player or enemy) | Need: stat-getter           | Stats live in `oIEntityValueModifierComputer` (in strings.json). Hook its `compute()` and apply a tag-keyed multiplier. |

### Spawn / generation

| Feature                                | Anchor                       | Next step                                                                                                  |
|----------------------------------------|------------------------------|------------------------------------------------------------------------------------------------------------|
| All enemies = crabs                    | Need: enemy-template picker  | `EntityCpntMethodPicker`, `AliasPicker`, `RefugeeArchetypePicker` (in strings.json) are pickers. The enemy version probably has a similar name; needs a Ghidra class-walk. Once found, hook the picker, force return = crab template id. |
| Modify NPCs (vendors / refugees)       | `RefugeeArchetypePicker`     | Decompile + hook to pin a chosen archetype.                                                                |
| Reward / chest content by difficulty   | Need: reward roller          | Xref `"_InitAllRewards"` (`FUN_1401e6030`) — it's a reward-type registrar; the actual roller will be a sibling. `oCDtRewardDefinition` is the entity class. |

### Seed / run

| Feature                                  | Anchor                          | Next step                                                                                                  |
|------------------------------------------|---------------------------------|------------------------------------------------------------------------------------------------------------|
| Per-chapter seed input                   | `Forced seed` (already mapped)  | The bool/value pair is one global. Hook the chapter-init function (xref `"Chapter 1 Complete"` etc.) and reseed per chapter. |
| Quest selection (enable/disable)         | Need: quest roller              | No direct anchor yet. Look for `quest` / `Quest` strings; if absent, the quest system probably re-uses `_InitAllRewards`-style entity drop tables. |

### Run-end / stats

| Feature                                | Anchor                          | Next step                                                                                                  |
|----------------------------------------|---------------------------------|------------------------------------------------------------------------------------------------------------|
| Win / Lose / Abandon counter per hero / difficulty / coop | `FUN_1401d6b10` (`Is in victory sequence`, `Is in defeat sequence`) + `Abandon` dispatchers | Hook the three dispatchers; record `(hero_id, difficulty, coop?)` to a JSON in `mods/<id>/state.json`. Read-only memory access — no game-state mutation needed. |
| Enable shapeshifter by default on Scarlet | Need: hero-load function       | No `Shapeshift` string found. Likely encoded as a class name. Walk Scarlet's cooked entity files for `oCDtEntityCpnt*Shapeshift*` and then xref. |

## Recommended first POC for `rsmm.hook` validation (task #6)

**Pick one of:**

1. **Win / Lose / Abandon counter** — pure read-side hooks on the
   three dispatchers in `FUN_1401d6b10` + `FUN_140291190`. No
   mutation, can't break a run, easiest to prove the API works.
2. **Difficulty multiplier hook** — pick the modifier-getter inside
   `FUN_1401d6b10`, multiply by N from Lua. Visible in-game
   immediately (enemies harder), trivial to roll back.

Either choice would prove the full chain: `rsmm.resolve(name) →
rsmm.hook(va, "sig", cb) → callback fires → modifies behavior →
unhook on mod disable`.

## Methodology used (so this is repeatable)

1. `python3` over `out/strings.json` bucketed by feature-keyword
   regex (see this commit's `_re/HOOKPOINTS.md` for the list).
2. `grep -rE "<exact string>" out/decompiled_all/` to find the
   containing functions.
3. Most "feature event" strings (`Skill propose`, `Camp Difficulty
   Modifier`, etc.) collect inside *two* functions:
     - a giant **registry** function (`FUN_1401d1850`,
       `FUN_1401d6b10`) that constructs the event/modifier name
       table at boot,
     - the actual **dispatcher** that takes the name and routes it.
   The registry is found first; the dispatcher is a Ghidra xref of
   the name string from outside the registry function.
4. To get the dispatcher we need a small Ghidra script —
   `docs/_re/scripts/xrefs_to.py` already exists; run it for each
   anchor string. That gives the consumer functions per feature.

Next pass should be a script that takes the list of anchor strings
from this doc and dumps decompiled bodies of every xrefing function
into `out/hookpoint_candidates/`. That's the menu we hook from.
