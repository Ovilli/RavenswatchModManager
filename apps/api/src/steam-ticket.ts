import { createHmac, randomUUID } from 'node:crypto';

/**
 * Mints the signed tickets the Stormancer backend accepts in place of a Steam ticket.
 *
 * Verifying a real Steam ticket needs a publisher Web API key for appid 2071280, which only
 * Passtech has. Proving who someone is does not: Steam OpenID (see `steam-openid.ts`) is free and
 * verified server-side. So this mints a short-lived ticket carrying what we established there, and
 * `services/stormancer/server/RsmmSteamService.cs` verifies it with the same shared key.
 *
 * Format: `rsmm1.<payload>.<signature>`, both base64url without padding, signature =
 * HMAC-SHA256 over the ASCII bytes of `"rsmm1." + payload`.
 *
 * The C# side pins this format in `services/stormancer/tests/TicketVectorTests.cs`. That vector is
 * the only contract between the two languages and `test/steam-ticket.test.ts` reproduces it, so a
 * change on either side fails a test instead of refusing every login in production.
 */

/** Ticket prefix, also the format version. A v2 would be a different prefix on both sides. */
export const TICKET_PREFIX = 'rsmm1';

/** How long a minted ticket stays usable. Must not exceed the grid's `maxTicketAgeSeconds`. */
export const DEFAULT_TICKET_TTL_SECONDS = 300;

/** The lowest possible SteamID64 (individual account, universe 1). */
const MIN_STEAM_ID64 = 76561197960265728n;

export interface SteamTicketClaims {
  /** SteamID64, as proven by Steam OpenID — never a value the client supplied. */
  steamId: string;
  /**
   * Whether Steam's public web API showed appid 2071280 in this account's library. False means
   * "could not tell" as often as "does not own" (a private profile hides the library), so the
   * backend treats it as a badge, never a gate.
   */
  ownsGame: boolean;
  /** Mod-pack fingerprint, or null for an unmodded game. */
  pack: string | null;
  /** Human-readable pack name, for the backend's log lines only. */
  packName: string | null;
}

export interface MintTicketOptions {
  ttlSeconds?: number;
  /** Unix seconds. Injectable so tests can pin the clock. */
  now?: number;
  /** Ticket id, for the backend's single-use check. Injectable for the format vector. */
  jti?: string;
}

const base64url = (input: Buffer): string => input.toString('base64url');

/**
 * Throws rather than minting a ticket that cannot be right — a malformed SteamID64 here would
 * become a verified identity for an account nobody owns.
 */
function assertSteamId64(steamId: string): void {
  if (!/^\d{17,20}$/.test(steamId)) {
    throw new Error(`not a SteamID64: ${JSON.stringify(steamId)}`);
  }
  if (BigInt(steamId) < MIN_STEAM_ID64) {
    throw new Error(`below the lowest possible SteamID64: ${steamId}`);
  }
}

/** Empty and whitespace-only mean "no pack", so two unmodded players match each other. */
const normalisePack = (value: string | null | undefined): string | null => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
};

export function mintSteamTicket(
  signingKey: string | Buffer,
  claims: SteamTicketClaims,
  options: MintTicketOptions = {},
): string {
  if (!signingKey || signingKey.length === 0) {
    throw new Error('refusing to mint a ticket with no signing key');
  }
  assertSteamId64(claims.steamId);

  const now = options.now ?? Math.floor(Date.now() / 1000);
  const ttl = options.ttlSeconds ?? DEFAULT_TICKET_TTL_SECONDS;
  if (!Number.isInteger(ttl) || ttl <= 0) {
    throw new Error(`ticket ttl must be a positive whole number of seconds, got ${ttl}`);
  }

  // Key order is part of the format: the C# vector signs exactly this JSON. Every field is always
  // present, so the bytes are a function of the claims alone.
  const payload = JSON.stringify({
    sid: claims.steamId,
    own: claims.ownsGame,
    pack: normalisePack(claims.pack),
    packName: normalisePack(claims.packName),
    iat: now,
    exp: now + ttl,
    jti: options.jti ?? randomUUID(),
  });

  return signPayload(signingKey, payload);
}

/**
 * Signs an already-serialised payload. Exported for the format vector, which has to sign a byte
 * sequence it did not build, and so cannot go through {@link mintSteamTicket}.
 */
export function signPayload(signingKey: string | Buffer, payloadJson: string): string {
  const payload = base64url(Buffer.from(payloadJson, 'utf8'));
  const signed = `${TICKET_PREFIX}.${payload}`;
  const signature = base64url(createHmac('sha256', signingKey).update(signed, 'ascii').digest());
  return `${signed}.${signature}`;
}
