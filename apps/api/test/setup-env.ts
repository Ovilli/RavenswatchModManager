import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { config as loadEnv } from 'dotenv';

// Populate process.env from the repo-root env files BEFORE any test module
// evaluates. The e2e suite reads readiness straight from process.env (it must
// not import src/env.ts, which throws on a missing DATABASE_URL), so without
// this the secrets in .env.local would never reach the readiness check and the
// suite would skip even locally. In CI these files are absent — load is a
// no-op and the suite stays skipped.
const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..', '..');
loadEnv({ path: resolve(root, '.env') });
loadEnv({ path: resolve(root, '.env.local') });
