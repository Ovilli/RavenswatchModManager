# rsmm.sdk.intermod

## `InterModRegistry.expose(self, mod_id: 'str', table: 'dict[str, Callable]', version: 'str' = '0.0.0', *, api_name: 'str | None' = None) -> 'None'`

Publish a table under `api_name` (defaults to `mod_id`).

## `InterModRegistry.require(self, name: 'str', version_spec: 'str' = '') -> "'InterModProxy'"`

(undocumented)
