// Netcode tweaks: extend the in-match P2P reconnection window so a dropped
// (non-host) co-op player has time to rejoin before being kicked.
//
// See docs/_re/MULTIPLAYER.md. The window is a baked uint8 (seconds) in the
// game's .data at preferred VA 0x1412e5ed3 (default 60). We rebase it to the
// live module and overwrite it, after verifying the known default bytes are
// present (so a game update that shifts .data is detected and skipped).
#pragma once

namespace rsmm {

// Apply the reconnect-window extension if armed (env RSMM_RECONNECT_SECONDS or
// the mods/.rsmm_extend_reconnect file marker). No-op + log otherwise. Returns
// true when the patch was written.
bool install_netcode_patches();

} // namespace rsmm
