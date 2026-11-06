#pragma once
// Selective (and master) audio mute, through FMOD's own exported API.
//
// WHY FMOD AND NOT THE GAME
// -------------------------
// Ravenswatch links FMOD as two separate DLLs next to the exe (fmod.dll =
// Core, fmodstudio.dll = Studio). Everything here is resolved by EXPORT NAME —
// the MSVC-mangled C++ methods the exe itself imports — so no
// data/symbols.json entry is involved and a game patch cannot move a target.
//
// THREE GRAINS
// ------------
//   * "all": the Core MASTER channel group, one detour on fmod.dll's
//     System::update. The game also plays a few sounds through Core directly
//     (System::playSound / createStream are in its import table), which no
//     Studio bus reaches; the Core master is the only switch over everything.
//   * a BUS path ("bus:/Music"): Studio System::getBus + Bus::setMute, applied
//     from a detour on Studio System::update. A bus mutes everything routed
//     through it, sub-buses included.
//   * an EVENT path or folder ("event:/Heroes/Red", or one full event path):
//     a detour on EventInstance::start reads the instance's description path
//     (cached per description) and drops a matching instance's volume to 0.
//     A detour on EventInstance::setVolume keeps it there while recording what
//     the game asked for, so un-muting restores the game's own volume. Every
//     instance started after the first selection is tracked, which is what
//     lets a selection change reach sounds already playing (music especially);
//     Studio handles are validated by FMOD, so a stale one just returns
//     FMOD_ERR_INVALID_HANDLE and is pruned.
//
// All FMOD calls the loader makes run inside FMOD calls the game made, on the
// game's own thread — never cross-thread from Lua.
//
// Mutes are RE-ASSERTED while selected (the game is free to toggle the same
// flags); a release is applied once, then the flag is the game's again.
#include <string>
#include <vector>

namespace rsmm {

// Hook the FMOD exports. Returns true when at least one grain is live. Safe
// when FMOD is not loaded (returns false and logs).
bool install_audio_hooks();

// Master mute ("all"). Any thread; applies on the next Core update.
void audio_set_mute(bool on);

// Replace the selected bus / event paths. Entries are "bus:/..." or
// "event:/..." (case-insensitive; an event entry matches itself and anything
// below it). Anything else is ignored. Any thread.
void audio_set_targets(const std::vector<std::string>& paths);

struct AudioStatus {
    bool               hooked;        // Core master grain live
    bool               studio_hooked; // bus + event grains live
    bool               muted;         // master mute requested
    int                systems;       // Core systems seen updating
    unsigned long long updates;       // Core update fires
    int                buses;         // bus targets
    int                buses_muted;   // bus targets found and muted by us
    int                events;        // event-path targets
    int                instances;     // event instances currently tracked
    int                instances_muted;
    int                last_error;    // last non-zero FMOD_RESULT from our calls
};
AudioStatus audio_status();

} // namespace rsmm
