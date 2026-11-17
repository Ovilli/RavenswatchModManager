# Host Crown 0.0.1

Standalone release candidate. In co-op, the crown sits to the left of the
elected host's HP bar, opposite the dash arrow.

Use the native nameplate SDK checkout and matching pattern database. This preview
requires the `nameplate_crown` content kind with `include_peers`, the
`R.nameplate.update_host_crowns()` API, and the `UiElement_SetVisible` alias
for game build `b9c3642884a8`. The currently installed RSMM kit does not
provide those together. The source archive asks RSMM to generate both UI
layouts from your own install.

For private co-op testing, disable the earlier solo crown preview, install
this archive into the mod library, and review `rsmm apply --dry-run` before
applying. Keep both clients on the same setup. The crown can appear briefly
before the first ownership update. The native hide/show operation passed a solo test. A live co-op run
recorded one visible crown across four nameplates. The player reported frame
skips. This build scans for nameplates on the gameplay thread every half second,
which warrants profiling before a public release.

To remove the mod, disable it and apply again to restore the original UI assets.
