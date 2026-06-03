# Multiplayer: disconnect / reconnect / "match closes when one player quits"

First-pass RE of why a Ravenswatch co-op match collapses when a player leaves,
and what is actually patchable. Source: live GhidraMCP session against the
shipped `Ravenswatch.exe` (addresses are image VAs, base `0x140000000`).

## Stack

Netcode is **Stormancer** (hosted P2P relay backend) layered over **Steam** +
**EOS**. Evidence: RTTI/strings `P2PStormancerConnection`, `oCStormancerSceneContext`,
`GameSession_Impl`, `PartyService::handleMemberDisconnected`,
`EP2PConnectionState`, `EOS_CET_Reconnection`, `SteamServersDisconnected_t`.
Implication: anything we change is client-side only; the Stormancer backend is
authoritative for session/party ownership, which bounds what a loader can do.

## There IS a built-in mid-match reconnection system

Ravenswatch already pauses the match on a drop and resumes on reconnect:

- Net messages `oCDtNetMsgMultiplayerReconnectPause` / `...Unpause`.
- UI `GameUis\Common_Ui\Reconnect_Notification.entity.ot`.
- `NetMsgReconnectOption`, `EOS: Next reconnection attempt in {} seconds`.

So a *transient* drop of a **non-host** peer is meant to be survivable. The pain
is (a) the reconnect window is short and (b) the **host** leaving is fatal.

## The per-peer connection state machine — `FUN_1402afaa0`

Ticks every peer in the global player array and drives `EP2PConnectionState`:

- Player array: base `DAT_141438fc0`, **stride 0x60**, count `DAT_141439140`.
  (A parallel pointer table `DAT_141439010`, stride 0xc qwords, indexes the same
  peers.)
- Per-peer connection-state enum at **`peer+0xCC`**: `3` = connected (skipped),
  others = `eConnecting/eInterrupted/eClosed/eClosing`.
- Per-peer timestamps: `peer+0xD0` (state-change time), `peer+0xD8` (reconnect
  window start). Elapsed seconds = `(QueryPerformanceCounter - ts) / DAT_14143b9c8`
  (perf freq).

### The timeout constants (baked config bytes — the levers)

Four single-byte values in `.data`, **only read here**, statically initialized
(no writer xref → compile-time constants). Defaults read straight from the
shipped exe:

| Addr | Default | Meaning (seconds) | Effect when elapsed ≥ value |
| --- | --- | --- | --- |
| `0x1412e5ed2` | **15** | interrupted → disconnect delay | peer goes `eInterrupted -> disconnect` |
| `0x1412e5ed5` | **5** | max **connecting** time | calls peer vtbl `+0x28` (stop) |
| `0x1412e5ed4` | **4** | reconnect-UI threshold | sets the "show reconnect notification" flag |
| **`0x1412e5ed3`** | **60** | **max reconnection time** | logs `"... -> stop - max reconnection time attempt"` → **`FUN_1402b4450(peer_idx)`** |

So a dropped non-host peer currently gets a **60-second** rejoin window (match
paused) before it is kicked. They are `uint8` seconds → max 255.

`FUN_1402b4450` = **remove that one peer** from the array (swap-with-last via
`FUN_1402b7000`, free via `FUN_1402b54b0`, `DAT_141439140--`). It does **not**
close the match — the remaining players continue. So extending `0x1412e5ed3`
lengthens the rejoin window for a dropped **non-host** peer; it never has to be
kicked if it returns in time.

## Why the WHOLE match still dies: host leave (no migration)

Two distinct flow-state keys exist:

- `Session_Disconnected_Go_To_Lobby` (140f0f318)
- `Session_Disconnected_From_Host_Go_To_Lobby` (140f0f3b8)

Neither has a direct string xref (they're flow-state keys resolved by
hash/table, not LEA). The second is the killer: when the **host** (Stormancer
session owner) leaves, there is no host-migration path, so every client is sent
to lobby. The reconnect state machine above only saves **non-host** peers.
**This is almost certainly what players hit** — the lobby host quitting.

## Verdict / feasibility

1. **Extend the rejoin window for non-host drops/quits — EASY, low risk.**
   Loader byte-patch `0x1412e5ed3` (and likely `_ed2`/`_ed5`) to a larger
   second count (bytes, so ≤255). Pure data write at a fixed RVA after module
   base — no detour needed. Net effect: a dropped player has up to ~minutes
   (match paused) to rejoin before being kicked. Open: confirm a clean "Quit to
   menu" routes a non-host through this reconnect path vs. a graceful-leave path
   that skips it (TODO: trace `PartyService::handleMemberDisconnected`).

2. **Survive the HOST leaving — HARD, maybe impossible client-side.**
   Needs host migration (elect a new Stormancer session owner). Stormancer is a
   hosted backend; ownership is likely server-enforced, so a client-only loader
   patch probably can't re-own the scene. Intercepting
   `Session_Disconnected_From_Host_Go_To_Lobby` to *not* go to lobby would leave
   clients in a dead scene. Requires deeper trace of `GameSession_Impl` /
   `oCStormancerSceneContext` ownership before any verdict.

3. **"Rejoin a match you intentionally left" — partially built-in, not full.**
   The reconnect/pause path covers returning within the window. A true late
   re-join of a match you cleanly left needs full state resync (run seed, entity
   state, progress) that the late-join path may never serialize. Unconfirmed.

## Confirmed addresses (rebase if the game patches)

| Symbol | VA | Role |
| --- | --- | --- |
| `FUN_1402afaa0` | `0x1402afaa0` | per-peer P2P connection-state tick |
| `FUN_1402b4450` | `0x1402b4450` | remove one peer from the session array |
| `DAT_1412e5ed3` | `0x1412e5ed3` | **max reconnection time (s)** — primary lever |
| `DAT_1412e5ed2/4/5` | `0x1412e5ed2/4/5` | interrupt-drop / UI / max-connect timeouts |
| `DAT_141438fc0` | `0x141438fc0` | player array base (stride 0x60) |
| `DAT_141439140` | `0x141439140` | player count |
| peer `+0xCC` | — | connection-state enum (3 = connected) |

## Shipped: reconnect-window extension (loader)

`src/loader/src/hook_netcode.cpp` (`install_netcode_patches`, wired in
`dllmain.cpp`) rebases `0x1412e5ed3` onto the live module and overwrites the
max-reconnection window. **Verify-then-patch**: it checks all four defaults
(`15/60/4/5`) are present first, so a game update that relocates `.data` is
detected and skipped rather than corrupting a random byte.

Arm it (opt-in, like the other engine hooks):

- env `RSMM_RECONNECT_SECONDS=1..255` (the new window), or
- touch `mods/.rsmm_extend_reconnect` (uses default 250 s).

**What this fixes:** a **non-host** peer that drops (crash / network blip) now
has up to ~4 min — match paused — for its client to auto-reconnect
(Stormancer/EOS already retry: `"Next reconnection attempt in {} seconds"`),
instead of being kicked at 60 s. That is genuine rejoin-after-drop.

**What it does NOT fix (still open):**

- **Host leaving** → `Session_Host_Abandon` /
  `Session_Disconnected_From_Host_Go_To_Lobby`. **Not fixable client-side**, and
  this is the wall, not a tunable. The game is **host-authoritative P2P**:
  - Clients receive the P2P session *from the host* (`StateWaitingP2PSessionFromHost`,
    `Can't find host info`, `Waiting P2P Session From Host`, `Is Session Host`).
  - Entity spawning/replication is **host-mastered**: `Peer spawned {} (owned by
    {}) but is not master. Please set mastership to Host or HostUnique` and
    `Host spawns the entity and replicates it to every other peer`.

  There is no host-migration path. A promoted client would have to re-own every
  host-mastered entity and re-seed the P2P session as the new authority — the
  Stormancer scene + replication model does not allow a client to reassign that
  mid-run. So the common "whole match closes" (host quit) cannot be patched
  away from the client; it would need a game/server change (host migration or a
  dedicated-session mode).
- **Full quit → relaunch → rejoin.** A clean quit tears down the client's
  session token, so a relaunched process has nothing to reconnect to. Extending
  the window can't help; this needs a re-join-by-invite/late-join path that the
  game may not expose.
- The party layer (`PartyService`, member list at `party+0x158`,
  `FUN_1408ddae0` removes a member) is separate from the GameSession peer array.

## Next steps

- Read the default byte values at `0x1412e5ed2..5` (current window length).
- Trace `PartyService::handleMemberDisconnected` + the graceful-leave path to
  confirm which quits enter the reconnect machine.
- Trace the host-leave → `Session_Disconnected_From_Host_Go_To_Lobby` caller to
  scope host-migration feasibility (likely a dead end, but worth confirming).
