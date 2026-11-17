# Native overhead host crown

Checkpoint: November 12, 2026. [Setup, SDK usage, reproduction steps, and next
verification](../../examples/native-host-crown/README.md). The original checkpoint ended before visual verification. The solo test below
confirmed rendering.

## Live observations, b9c3642884a8, 2026-11-11

Read-only diagnostic from a captured solo hero located its component named
`Life Bar Spawner` (`oCEntityCpntEntitySpawner`). Its +0x88 pointer resolved
to an `oCEntity` containing 133 components. A separate read-only process
inspection confirmed these live links using MSVC RTTI:

| Component | Offset | Native widget | Vtable RVA |
|---|---|---|---|
| Life Bar Game Ui | 0x88 | oCUILayoutWindow | 0xf4f808 |
| Username Window UI | 0x138 | oCUILayoutWindow | 0xf4f808 |
| Top Bar Picture | 0x138, 0x178 | oCUIPicture | 0xf50d18 |
| Top Bar Text UI | 0x138, 0x1a8 | oCUILabel | 0xf4f6e0 |
| Top Bar Text With Icon UI | 0x138, 0x1a8 | oCUILabel | 0xf4f6e0 |

These are the nameplates over characters. `HUD_Hero_Miniature` is the wrong
surface for this request. The original broad diagnostic exhausted its read
budget there; its `captured` status was not sufficient proof. The corrected
probe only reports success after finding the overhead label, without truncation.
The attempted hot reload produced no acknowledgement in that session's log;
the successful second inspection read the captured spawner externally instead.

No multiplayer host identity was established in the solo capture (both owner
and session host were unknown). No new engine call, hook, or UI write was used.
The three live vtables are `va` symbols, not proof that any new function is safe
to call. Serializer candidates remain `unverified` and cannot resolve at runtime.

## Native layout prototype

`engine/nameplate_crown.py::add_crown` is exposed through the experimental
`nameplate_crown` content kind. It clones the retail `Host_Picture` descriptor
from `Hero_Display` into `Life_Bar_Hero_Common` as a child of
`Top_Bar_Text_Frame`, using the stock `BookMenu/LeaderPins.png` resource.
The native builder owns and draws it; there is no overlay or executable patch.

The serializer's exact versions gate the edit: `oC2dElementDesc` 1.14 and
`oC2dPictureDesc` 1.6. The base serialized prefix ends with a child-vector count
at offset 45. An added object must appear in the object directory AND the
parent's child vector. It is a UI sub-object, not an entity component, so the
entity's component vector stays byte-identical. Existing object IDs do not move.

`preview=true` is a SOLO placement test that displays the crown on every
applicable nameplate. The default makes no change. It is not host detection.
Stock aspect/style/visibility flags are preserved, not guessed. Geometry and
texture loading still require visual validation in the game, including peer
variants, different heroes, death/revive and scene changes.

## Remaining release work

After placement is proven, implement native per-hero visibility through a
mapped, validated SDK API. Compare the actual hero entity's network owner
against the elected session host; never infer host from hero or roster order.
Unknown identity must hide the crown. Validate host and guest views before
including it in the public QoL mod. Do not publish this development preview.

## Solo rendering and visibility evidence (November 14–15)

The player confirmed the crown appeared above their character in solo. A live
read-only capture found `RSMM_Host_Crown` as an `oCUIPicture` under
`Top_Bar_Text_Frame`, with a layout size of 16 × 13 pixels. The renderer
walks first child at `+0x2a8` and sibling at `+0x08` with an all-ones sentinel.
The child points back to its parent at `+0x298`. The separate vector at
`+0x310` did not describe this live tree. `R.nameplate.inspect()` uses fresh
lookups and reports the network owner comparison without returning pointers.

After restarting, the temporary observer recorded the game calling
`UiElement_SetVisible` on `Available_Skill_Frame`. Visible and immediate were
0 and 1 in their low bytes. The full immediate register included unrelated
upper bits. The widget flags changed from `0x30` to `0x20` and alpha became zero.
That verifies the normal hide path for that frame. On November 16, a controlled test hid the crown itself (flag clear, alpha 0)
and restored it (flag set, alpha 1). The symbol is now callable by name.
The solo test did not establish the co-op host-to-owner join.

The stock `Life_Bar_Hero_Peer` asset also accepts the crown descriptor and
contains `Top_Bar_Text_Frame`. Its cooked component table has `Life Bar Game Ui`
but lacks the local `Username Window UI` component. The runtime peer lookup
will therefore need to locate the frame through the game UI widget tree.

The private co-op example builds both layouts and calls
`R.nameplate.update_host_crowns()` from the gameplay scheduler. The SDK
reacquires the picture on each update and shows it only for a known owner
matching the elected host. The test assets start visible, so expect a possible
flash before the first update. Verify both clients, roster changes, and
initial visibility before release.
