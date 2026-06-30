# API security notes

Access model and operational hardening for the rsmm API.

## Access model

- **Public (no auth):** browse/search mods, mod detail, download (rate-limited),
  reviews list, public collections, **approved** guides, user profiles
  (id/name/handle/image only — never email), `/api/health`, `/api/auth-config`,
  and anonymous telemetry (`/run`, `/crash`, rate-limited).
- **Authenticated (+ email-verified in prod):** publish, new versions, edits,
  image presign, own reviews, create collections/guides, avatar.
- **Owner-only:** every mutation checks `ownerId === user.id` → 403 otherwise.
- **Admin-only:** guide approve/reject + `/api/guides/pending`. Admins are the
  user ids in the `ADMIN_USER_IDS` env var (comma-separated). A non-admin
  hitting `/pending` gets a correct **403** — add your user id to moderate.

## Rate limiting

`createRateLimiter` (`src/rate-limit.ts`) requires a unique `name` per limiter;
the counter key is `name:ip-or-user`, so limiters never share a bucket.

- Default backend is **in-memory, per-process**. On a multi-instance / serverless
  deploy each instance keeps its own counters, so the effective limit is
  `maxHits × instances`.
- Set **`UPSTASH_REDIS_REST_URL`** + **`UPSTASH_REDIS_REST_TOKEN`** to switch to a
  shared Upstash Redis backend (correct across all instances, dependency-free).
  Recommended in production so the auth (10/min) and upload (5/hr) limits hold
  globally. If Upstash is unreachable the limiter falls back to in-memory rather
  than failing requests.

## Uploads

- Presigned S3 PUTs fix content-type + length; mod zips also pin a SHA-256
  checksum. Object keys derive from a regex-validated slug — no path traversal.
- A version is only treated as final once the scan/finalize endpoint confirms the
  object exists in S3 (`objectExists` HEAD), so a listing can't point at a missing
  download.
- VirusTotal scanning is **optional** — unset `VIRUS_TOTAL_API_KEY` and uploads
  still publish (scan reported as skipped). The free VT tier forbids
  commercial/service use; use an appropriately-licensed key if you enable it.

## CDN / object serving (config, not code)

User-uploaded images are served from the S3/CDN host, not the API, so the API's
response headers don't cover them. On the bucket/CDN, serve objects with
`X-Content-Type-Options: nosniff` and the stored content-type so a non-image
uploaded under an image key can't be sniffed into something executable.

## Secrets

`BETTER_AUTH_SECRET` and `DATABASE_URL` are required (the process refuses to boot
without them) — no insecure defaults. Keep `BETTER_AUTH_SECRET` high-entropy.
Rotate any key that leaks (e.g. pasted into a chat/log).
