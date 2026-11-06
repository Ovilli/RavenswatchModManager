// Netcode tweaks for co-op drops. Both opt-in, both verify-then-write, both
// located through pattern-resolved symbols (see hook_netcode.cpp):
//
//  * reconnect window — how long a dropped EOS tunnel may reconnect before the
//    peer is removed (stock 60 s). Env RSMM_RECONNECT_SECONDS=1..255 or the
//    mods/.rsmm_extend_reconnect marker (250 s).
//  * RakNet P2P timeout — how long the co-op mesh tolerates silence from a
//    peer before ID_CONNECTION_LOST (stock 10 s; losing the HOST this way ends
//    the session). Env RSMM_P2P_TIMEOUT_SECONDS=10..300 or the
//    mods/.rsmm_p2p_timeout marker (60 s).
//
// See apps/docs/src/content/docs/reverse-engineering/multiplayer.md.
#pragma once

namespace rsmm {

// Apply whichever patches are armed. No-op + log otherwise. Returns true when
// at least one patch was written.
bool install_netcode_patches();

} // namespace rsmm
