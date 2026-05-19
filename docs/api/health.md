# rsmm.sdk.health

## `Health.disabled_mods(self) -> 'set[str]'`

(undocumented)

## `Health.re_enable(self, mod_id: 'str') -> 'None'`

User manually re-enables after fixing the crash.

## `Health.record_crash(self, mod_id: 'str', error: 'str' = '') -> 'HealthState'`

Bump the mod's crash counter, persist, return the updated state.

If the mod hits `threshold`, mark `disabled_by_health=True`. The
applier consults this on the next run.
