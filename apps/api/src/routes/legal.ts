import { Hono } from 'hono';
import { env, impressumConfigured } from '../env';
import type { AppEnv } from '../types';

export const legalRouter = new Hono<AppEnv>();

// Public — the whole point of §5 DDG is that this is reachable with zero
// conditions (no auth, no gating). Values come from env, never from source,
// so the operator's home address never lands in git history.
legalRouter.get('/impressum', (c) => {
  if (!impressumConfigured()) {
    return c.json({ configured: false }, 503);
  }
  return c.json({
    configured: true,
    name: env.impressum.name,
    address: env.impressum.address,
    email: env.impressum.email,
  });
});
