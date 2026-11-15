// Keep gameplay mods out of PUBLIC matchmaking (see hook_online_gate.cpp).
#pragma once

namespace rsmm {

// Arms the gate when `rsmm apply` left <game>/mods/.rsmm_gameplay behind.
// Returns true when the matchmaking hook is live.
bool install_online_gate();

} // namespace rsmm
