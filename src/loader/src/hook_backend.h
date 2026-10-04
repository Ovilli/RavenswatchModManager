#pragma once
// Online-backend redirect + Steam web-ticket identity probe. See hook_backend.cpp.

namespace rsmm {

// Log whether the backend redirect is armed. The redirect itself lives in the
// exported WinHttpConnect / WinHttpOpenRequest wrappers and needs no install
// step; this only reports the configuration once the loader log is up.
bool install_backend_redirect();

} // namespace rsmm
