# rsmm.sdk.repo

Distribution: `repo.json` schema + SHA256/Ed25519 sign + verify.

Open spec. No central host. Anyone can publish a `repo.json` at a URL of
their choice; users add it with `rsmm repo add <url>`.

Signing is optional but recommended. We use Ed25519 from `cryptography`
when available and fall back to "unsigned mode" otherwise. Keys live in
`~/.rsmm/keys/`:

    <id>.pub        # base64 Ed25519 public key
    <id>.key        # base64 Ed25519 private key (mode 0600)

:::note
Auto-generated from `@sdk_export` registrations by `rsmm docs-gen`. Edit the docstrings in the source module, not this page.
:::

## `repo`

### `repo.sha256_file`

```python
repo.sha256_file(path: 'Path') -> 'str'
```

Hex SHA256 of a file, streamed (no full-file buffering).

The integrity primitive behind `repo.json` manifests and
:func:`sign_file` / :func:`verify_file`.

### `repo.sign_file`

```python
repo.sign_file(path: 'Path', private_key_path: 'Path') -> 'str'
```

Return base64 Ed25519 signature of `path`'s SHA256 digest.

Signing the digest (not the whole file) lets verifiers stream-hash
without buffering the file.

### `repo.verify_file`

```python
repo.verify_file(path: 'Path', sig_b64: 'str', public_key_path: 'Path') -> 'bool'
```

Verify a base64 Ed25519 signature over `path`'s SHA256 digest.

Returns ``True`` if ``sig_b64`` (from :func:`sign_file`) matches under
``public_key_path``, ``False`` otherwise. Raises ``RepoError`` if the
optional ``cryptography`` package is missing.
