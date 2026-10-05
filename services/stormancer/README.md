# Ravenswatch backend (Stormancer)

An experimental replacement for Passtech's online backend: login, party codes, friends and
matchmaking. It runs the real Stormancer server (published on NuGet) with Stormancer's MIT-licensed
server plugins, so it speaks the same protocol the game's built-in client already uses.

**Status: runs locally, not yet connected to the game.** Nothing points Ravenswatch at it yet,
and nothing here is deployed publicly. Login and mod-pack matching are implemented and unit-tested
(`tests/`), but no real client has authenticated against them.

## Why

The game's online features all go through Passtech's Stormancer cluster
(`dt-live*.passtechgames.com`, UDP 30100). Where an ISP blocks that route (Egypt, Russia) the game
shows no party code and acts as if it were offline. Running our own backend also lets us fix
behaviour Passtech's doesn't: a party stays joinable while its run is in progress (see
`server/PartyGuard.cs`), and lobbies are matched by mod pack — the reason to run it for a modded
game at all (see **Modded games** below).

## What the game expects

From the game's own log (`<game>/_Logs/logs_*.txt`):

| Step | Passtech | Here |
| --- | --- | --- |
| Federation | `https://dt-live.passtechgames.com/_federation` | `http://localhost:8090/_federation` |
| Transport | RakNet UDP `:30100` | RakNet UDP `:30100` |
| App | `darktales/live-1-05-01` | same (`deploy/local.profile.json`) |
| Scenes | `authenticator`, `friends`, `party-manager`, `party-<guid>`, `matchmaking` | same, created by the plugins |
| Party protocol | `PartyService 2022-06-09.1`, `PartyManagement 2020-05-20.1`, revision `2020-08-21.1` | identical (current plugin source) |

## Run it

Needs the .NET SDK (8 or newer).

```sh
./run-local.sh        # starts a grid in grid/ and deploys server/
./run-local.sh stop
```

The grid logs to `grid/grid.log`. Runtime data (`grid/data`, `grid/tmp`) and the CLI (`.tools/`)
are gitignored.

Unit tests (ticket verification, the mod-pack registry, the cross-language vector):

```sh
dotnet test tests/
```

## Configuration

`deploy/app-config.json` is the app's config.

### Identity (`rsmm`)

Steam's own `ISteamUserAuth/AuthenticateUserTicket` needs a **publisher** Web API key for appid
2071280. Only Passtech has one, so that path is permanently closed here — a regular user key gets a
403. Verifying ownership, though, does *not* need a publisher key, and neither does proving who
someone is. So identity is established outside the game and carried in as a ticket:

1. The mod manager opens **Steam OpenID** (`steamcommunity.com/openid/login`) in the system
   browser. No key, no publisher status; the RSMM API verifies the response server-side and gets a
   SteamID64 it can trust.
2. The API optionally asks Steam's public web API — with a **free** key — whether that account owns
   appid 2071280 (`IPlayerService/GetOwnedGames`, `ISteamUserStats/GetPlayerAchievements`). Both are
   gated on the profile's *game details* privacy, so a private profile answers nothing. That makes
   ownership a badge, never a gate: "could not tell" is far more common than "does not own".
3. The API mints a short-lived signed ticket carrying the SteamID64, the ownership flag and the
   player's mod-pack fingerprint.
4. The game sends that ticket where a Steam ticket would go. `server/RsmmSteamService.cs` spots the
   `rsmm1.` prefix, verifies it against our own key, and returns the SteamID64 — so the stock Steam
   auth provider creates the user and session exactly as it would for a real ticket. **No new auth
   provider and no client protocol change**; the only thing that changes is which bytes are in the
   ticket field. A ticket without the prefix still goes to Steam untouched.

Nothing in that chain trusts the game client. Every field was decided by the API after it verified
the Steam login. The client only ferries the ticket.

| Key | Meaning |
| --- | --- |
| `ticketKeys` | Secret-store paths of the HMAC-SHA256 signing keys. More than one so a key can be rotated: a ticket is accepted if **any** verifies it, so the new key can be deployed before the mint side switches. |
| `requireVerifiedIdentity` | Refuse logins with no valid ticket. **Default off** — with it on and no loader able to supply a ticket, nobody can log in at all. |
| `enforceModPack` | Refuse party joins across different mod packs. |
| `maxTicketAgeSeconds` | How long a minted ticket stays usable (600). Short, because it is what bounds replay across a grid restart. |
| `clockSkewSeconds` | Tolerance for a mint-side clock that disagrees with ours (60). |

The signing key never goes in this repo. Create it in the grid's secret store, the same way as the
Steam key:

Run it **from `grid/`**, with a grid already started, and with `DOTNET_ROLL_FORWARD=Major` — the
same three things `run-local.sh` arranges for itself:

- **From `grid/`**, because the `manage` verb comes from the `Stormancer.Management.CLI` plugin
  listed in `grid/bootstrapper.config.json`. Run from anywhere else, the bootstrapper writes a fresh
  config without that plugin, builds a second ~100MB grid into `.stormancer/` there, and then fails
  with `Unrecognized command or argument 'manage'`.
- **With a grid up** (`./run-local.sh`), because it talks to the cluster's admin API on `:8091`.
- **With `DOTNET_ROLL_FORWARD=Major`**, because the CLI targets .NET 8 and a machine with only a
  newer runtime otherwise fails with "You must install or update .NET".

The store has to exist before a secret can go into it. `manage secrets update` only writes into an
existing one — despite its help text reading "Create or update a secrets store", it answers
`Secret store not found.` — so creating it is a separate command group, `secrets-store`.

```sh
cd services/stormancer
./run-local.sh                      # if the grid is not already up
cd grid
export DOTNET_ROLL_FORWARD=Major

# 1. a 32-byte random key (or use your own: head -c 32 /dev/urandom > /tmp/ticketKey.bin)
../.tools/stormancer manage secrets generate --size 32 -o /tmp/ticketKey.bin

# 2. the store, once per account
../.tools/stormancer manage secrets-store create --cluster local --account darktales --id rsmm

# 3. the key itself, at the path app-config.json points to (darktales/rsmm/ticketKey)
../.tools/stormancer manage secrets update --cluster local --account darktales \
    --store rsmm --id ticketKey --path /tmp/ticketKey.bin
```

`manage secrets-store list --cluster local --account darktales` shows what exists. The same two
steps apply to the `steam` store if a publisher key ever arrives.

With no key configured every RSMM ticket is refused — it fails closed, and the first authentication
logs `RSMM identity configuration` with `ticketKeys: 0` so a mistyped path is visible in `grid.log`
rather than silently accepting nothing.

The ticket format is `rsmm1.<payload>.<signature>`, both base64url, signature = HMAC-SHA256 over the
ASCII bytes of `"rsmm1." + payload`. `tests/TicketVectorTests.cs` pins it against a vector derived
outside this codebase (Python `hmac`), and **the TypeScript minter has to reproduce that vector** —
it is the only contract between the two languages, and a mismatch refuses every login.

HMAC and not a signature scheme is a deliberate, revisitable choice: the grid holds the same key the
minter does, so a compromised grid can mint identities. Ed25519 (grid holds only a public key) is
better and is the upgrade path, but .NET 8 has no in-box Ed25519 and adding BouncyCastle risks the
dependency-pin breakage documented in `server/RsmmBackend.csproj`. Revisit before deploying the grid
anywhere we do not control.

### Steam (`steam`)

- `appId`: `2071280` (set).
- `backendIdentity`: **`Ravenswatch`** (set). Confirmed 2026-10-04 by the loader's identity probe
  (`hook_backend.cpp` logs `[backend] Steam web-ticket identity`), which is the only way to get it:
  the game fills it at runtime and it is not a literal in the exe or the game data. The probe sees
  three identities in one session and only the first is Stormancer's — `Ravenswatch`,
  `2071280MyNacon`, and `epiconlineservices` (Epic's). Read the whole log, not the tail: a tail that
  happened to show only the other two is how this was briefly recorded wrong.
- `apiKey`: `darktales/steam/apiKey`, a secret in the grid's `steam` secrets store, and it must be a
  **publisher** key to be of any use to the plugin — see below. Ticket validation needs one
  regardless, and only Passtech has it.

#### The plugin sends every Steam call to the publisher host

`SteamService` hardcodes `private const string ApiRoot = "https://partner.steam-api.com"`. That host
accepts **only** a publisher key: a perfectly valid free key gets `403` there and `200` on
`api.steampowered.com` (both measured 2026-10-04). Because it is a `const`, no configuration
redirects it, and its own fallback does not help — `TryGetAsync` retries on the public host only when
the request throws `HttpRequestException`, i.e. a network failure. A `403` is a *successful* HTTP
exchange, so the retry never runs and the caller's `EnsureSuccessStatusCode()` throws.

The consequence is not limited to ticket validation: `SteamAuthenticationProvider.Authenticate`
calls `GetPlayerSummary` immediately after a ticket is accepted, so with a free key the whole login
died on a profile lookup *after* authentication had succeeded — a `403` naming nothing to do with
auth. `SteamProfiles.cs` issues that request itself, against the public host, with the key read from
the secret store; `GetPlayerSummaries` has never needed a publisher key.

A misstored key is otherwise invisible, since Steam answers `403` identically for a missing key, a
wrong key and a correct key with a trailing newline. `RsmmSteamService` logs the key's *shape* at
startup (byte length, length after trim, whether it is 32 hex characters) and never its value.

### The game never falls back to anonymous auth

Observed 2026-10-04: the client tries the `steam` provider only. When it is refused it logs
`Login failed : Authentication refused by steam.` and disconnects, with no second attempt at
`ephemeral` or `deviceidentifier`. **The anonymous tier is unreachable from Ravenswatch**, so the
RSMM ticket is not an optimisation — it is the only way a real client can log in. Those providers
stay enabled for clients we write ourselves.

### Local testing without any key (`trustUnverifiedSteamTickets`)

**Insecure. Never for a deployment.** Because the game only offers a Steam ticket and we cannot
validate one, there is otherwise no way to drive the backend with a real client until the ticket
path is finished. With this on, `RsmmSteamService` reads the SteamID64 out of the ticket *without
validating it* — so anyone who can reach the authenticator can log in as any Steam account by
writing an id into a blob. It logs a WARN naming itself on every use.

The id is found by structure, not at a fixed offset: every 8-byte little-endian window is tested
against the shape of an individual account id (universe 1, type 1), the conventional offset 12 wins
when several match, and an ambiguous ticket is refused rather than guessed.

Prefer the environment variable so no insecure value is committed (a test fails if
`trustUnverifiedSteamTickets` is ever true in `app-config.json`):

```sh
cd services/stormancer
RSMM_TRUST_UNVERIFIED_STEAM_TICKETS=1 ./run-local.sh
```

Verified end to end 2026-10-04 with a real game client: login, user creation with the real SteamID64
and persona name, session, and party creation.

## Modded games

Ravenswatch is host-authoritative P2P over a shared asset set, so a party whose members applied
different mods is a party that desyncs. Passtech's backend cannot know about mods. Ours does,
because the pack fingerprint rides in the login ticket the mod manager minted — the component that
knows which mods are applied is the one vouching for the player.

- At authentication, `RsmmSteamService` stages the verified identity and its pack.
- At login, `ModPackSessionHandler` re-keys it onto the Stormancer user id (the user id does not
  exist earlier), giving party handlers a cheap `ModPackRegistry.ForUser` lookup with no session
  round-trip.
- On join, `PartyGuard` refuses a member whose pack differs, with reason `party.modPackMismatch`.

It **fails open**: a member whose pack is unknown — an unverified login, or anyone who connected
before this was deployed — is never refused, because "unknown" and "different" are not the same
thing and refusing on unknown would empty every party during a rollout.

`ModPackRegistry` is process-wide, like `RunTracker`: correct on a single-node grid, where the
authenticator and party scenes share a process. A multi-node grid needs it in the cluster's
distributed cache.

## How the game picks a backend

The game has a built-in setting, `EndPointApp`, registered next to `Accepted EULA` in
`_Save/GameSettings.ini` (not written while it holds the default). It selects the server list
(code at `0x14032a5xx` in the 2026-10 build):

| Value | Name | Endpoints | Branch |
| --- | --- | --- | --- |
| 0 | Live (default) | `https://dt-live`, `https://dt-live-2` | `main` |
| 1 | Beta | same as Live | `beta-server` |
| 2 | Dev | `http://dt-dev.passtechgames.com:8888` | `dev-server` |
| 3 | Test | `https://dt-live-3` | `test-server` |
| 4 | LocalDev | `http://localhost` (port 80) | `dev-server` |

`LocalDev` means a local test needs no exe patch at all, only something answering on port 80.
Players elsewhere need a real redirect (loader work).

## Connecting a player

On the player's machine, with the loader up to date (`rsmm update-loader`):

```sh
rsmm backend http://85.214.117.164:8090
```

That is the whole setup, on Windows and Linux alike. It writes the address to
`<game>/mods/.rsmm_backend`, which the loader reads at every game start, so there is no `setx`, no
Steam restart and no launch-option variable (on Linux the launch option is still
`WINEDLLOVERRIDES="winhttp=n,b" %command%`; on Windows there is none). `rsmm backend off` goes back
to the official servers, and `rsmm backend` on its own shows the state.

It also checks the things that, when wrong, make the redirect silently do nothing, each of which has
cost a tester an evening:

| Check | What goes wrong without it |
| --- | --- |
| **Which game folder** rsmm is looking at, and where that answer came from | With two Steam libraries auto-detection can pick the install that is not being played, so `rsmm log` shows a log that never updates. Pass `--game-dir`, or set `RSMM_GAME_DIR` once. |
| **Whether the installed loader can redirect** | A loader older than v26 is installed, accepts the setting, and ignores it. A `winhttp.dll` of exactly 713160 bytes is Proton's/Windows' own, i.e. no loader at all. |
| **The address itself** | The loader does not fail on a bad address, it logs one line and does nothing: `https://`, a path, IPv6 and a port out of range are all ignored. They are refused here with the reason. `85.214.117.164:8090/` is accepted and cleaned up. |
| **`RSMM_BACKEND_URL` in the environment** | It beats the file. A leftover `setx` keeps the old address no matter what the file says. |
| **The server's answer** (`/_federation`) | A server whose `publicIp` / `loadBalancedIp` are still `localhost` answers the HTTP request and then tells every player to connect to *their own* machine, which looks like a problem on the player's side. |
| **The loader's own log** | Shows the `[backend] redirected …` line from the last launch and how old the log is. |

`rsmm apply` keeps the address: it empties `<game>/mods/` on every run, and wiping a setting the
player made on purpose silently sent the game back to the official servers.

## Known gaps

- **Minting tickets**: the mechanism exists and is unit-tested — `apps/api/src/steam-openid.ts`
  (OpenID verification + the free-key ownership probe) and `apps/api/src/steam-ticket.ts` (the
  minter, which reproduces this repo's format vector). What is missing is the HTTP route that joins
  them: a `/api/steam-auth/start` → `/callback` pair on the `desktop-auth.ts` relay pattern, which
  then hands the ticket to the app. Until that exists nothing mints a ticket in anger, so logins
  fall through to the anonymous `deviceidentifier` tier.
- **The pack fingerprint**: the ticket has a field for it, but nothing computes it yet. It has to be
  a stable hash of the applied mod set (from `.rsmm_state.json`), identical on two machines that
  applied the same mods, or every party is a mismatch.
- **Getting the ticket into the game**: the client has to put the ticket in the field it currently
  fills with a Steam ticket. That is loader work (hook the ticket source) and has not been done, so
  the ticket path is unit-tested but has never carried a real login.
- **Steam ticket login**: `backendIdentity` is now known, but validation still needs Passtech's
  publisher key, so this path stays closed and is not the one this backend relies on.
- ~~**Pointing the game here**~~: done. `src/loader/src/hook_backend.cpp` rewrites the host at the
  WinHTTP layer (the loader IS the game's `winhttp.dll`), so no exe patch and no `EndPointApp`
  change are needed. See **Connecting a player** below.
- ~~**Federation transports**~~: resolved 2026-10-04. Passtech's `/_federation` also lists
  `"transports": {"raknet": [...]}` and ours does not, but it does not matter: the scene tokens
  carry the RakNet endpoint and a real client connected on `localhost:30100`
  (`ID_CONNECTION_REQUEST_ACCEPTED`, `Completed connection [local]`).
- **Late-join guard**: `PartyGuard` refuses joins on two signals (member in a started game
  session, or all members Ready). Which one Ravenswatch triggers is unknown until a real session.
  `RunTracker` is process-wide, so it is only correct on a single-node grid.
- **Licensing**: the Stormancer server packages on NuGet carry no licence, and the node has a
  `licensekey` setting it did not ask for locally. Ask Stormancer before any public deployment.
  Ask Passtech too.

## Version pins (`server/RsmmBackend.csproj`)

The plugins are prereleases built against slightly different dependency versions. Without the pins
the host's dependency registration aborts halfway and later services go missing; the grid only
reports "failed to start" or an unrelated "not registered" error. `server/Program.cs` prints any
fatal host exception to stdout, because stdout is the only output the grid keeps.

- `Stormancer.Server.Hosting` 2.1.1.2-pre: 2.0.1.1 lacks `Scene.AuthorizeP2P`.
- `Stormancer.Server.Plugins.Database.EntityFrameworkCore` 0.1.0.18-pre: Users pulls 0.1.0.17-pre.
- `Stormancer.Server.Plugins.Analytics` 2.2.0-pre: GameSession needs it.
- `Stormancer.Server.Plugins.Party` **5.3.0-pre**, and `Stormancer.Server.Plugins.Steam` 4.3.0-pre to
  match (4.3.0.2-pre requires Party ≥ 5.3.0.8-pre): Party 5.3.0.1-pre changed
  `PartySettingsDto.CustomData` / `PartySettingsUpdateDto.CustomData` from `string` to `byte[]`, and
  Ravenswatch's client still sends a string. On a newer Party plugin every party settings update fails
  with `Unexpected msgpack code 217 (str 8)` and the game logs `_UpdatePartyData - Exception Caught`
  several times a second, though the invitation code is still generated. Those two fields are the only
  wire difference between 5.3.0-pre and 5.3.0.8-pre. Do not bump Party past 5.3.0-pre without
  re-checking them.

## Linux notes (`grid/default.json`)

- API ports moved to 8090/8091/8443: the defaults (80/81/443) need root.
- `cluster.endpoint` is `0.0.0.0:{n2nPort}`, not `*:{n2nPort}`: `*` binds IPv4 and IPv6, and
  Linux's dual-stack IPv6 socket already covers IPv4, so the second bind fails with "Address
  already in use".
