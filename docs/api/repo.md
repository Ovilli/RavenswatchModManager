# rsmm.sdk.repo

## `repo.sha256_file(path: 'Path') -> 'str'`

(undocumented)

## `repo.sign_file(path: 'Path', private_key_path: 'Path') -> 'str'`

Return base64 Ed25519 signature of `path`'s SHA256 digest.

Signing the digest (not the whole file) lets verifiers stream-hash
without buffering the file.

## `repo.verify_file(path: 'Path', sig_b64: 'str', public_key_path: 'Path') -> 'bool'`

(undocumented)
