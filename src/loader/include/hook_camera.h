#pragma once
// Native, blended camera zoom through the game's own camera modifier tree.
//
// WHY THIS EXISTS
// ---------------
// Writing the live camera's distance setting (what R.camera.set does) lands on
// the next frame: a snap. The game's smooth camera changes (Kintaro mounting,
// Melusine's wisp) are not tweens of those settings; every frame the scene's
// camera state is rebuilt by a tree of modifiers rooted at CameraSceneContext
// +0x78, and each modifier eases its own weight in or out over its own duration
// (CameraModifier_Evaluate). The engine ships an oCZoomCameraModifier that
// scales the eye's distance to the look-at point by a factor, weighted by that
// blend. Nothing in the game instantiates it; this file does.
//
// HOW
// ---
// The loader owns 1 + kSteps zoom modifiers in its own memory (the game never
// frees a child: the base destructor frees only the child ARRAY). A base
// modifier holds the settled factor F at weight 1; each zoom request takes a
// step modifier with factor s that fades in with the engine's cosine curve.
// When a step has fully faded in, its factor is folded into F and the step
// leaves the tree.
//
// Every change to a tree happens inside a detour on CameraModifier_Evaluate,
// when the modifier being evaluated is a camera root and before the original
// runs: the thread that owns that tree, between two evaluations. Lua only
// queues requests under a mutex.
//
// Which camera: TopDownCamera_Activate (detoured) records the camera's own
// position and near/far modifiers. The zoom is applied only while one of them
// is in the adopted tree, and is kept behind them (the position modifier at
// weight 1 overwrites the eye); with none there (a menu, an end screen) ours
// leave the tree and the factor waits. A cinematic's modifiers added after ours
// stay after them, so cutscenes are not zoomed. More than one camera tree can
// be alive at once (the menu-side scene stays beside a run, and the end-of-run
// book is drawn through it): only one is adopted, and ours are removed from any
// other on its own evaluation.
//
// The camera state persists between frames and a blending position modifier
// lerps from it, so the zoomed eye would feed back into the next frame's blend.
// Before each evaluation the detour puts back the unzoomed eye, but only when
// the state is still exactly what the last evaluation left.
//
// The settled factor survives a scene change (a new root is adopted and the
// base modifier re-added); camera_zoom_reset returns to 1.
namespace rsmm {

// Detour CameraModifier_Evaluate and TopDownCamera_Activate, and resolve
// CameraModifier_AddChild. Gated on
// va_globals_trusted() (the vftables that identify the root are VA globals).
bool install_camera_hooks();

bool camera_zoom_armed();

// Queue a zoom by `step` (multiplies the eye distance; < 1 moves in) blended
// over `seconds` (<= 0 is instant). False when not armed or `step` is not a
// finite value in [0.05, 20].
bool camera_zoom_by(float step, float seconds);

// Queue a return to factor 1 over `seconds`.
bool camera_zoom_reset(float seconds);

// `target`: the factor once every queued step has blended in (what to clamp
// against). `current`: the factor applied on the last evaluated frame.
void camera_zoom_factor(float* target, float* current);

} // namespace rsmm
