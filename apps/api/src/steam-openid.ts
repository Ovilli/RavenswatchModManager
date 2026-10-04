/**
 * Steam OpenID 2.0 sign-in, and the free-key ownership probe.
 *
 * This is the whole reason the backend can verify players without Passtech's publisher key.
 * `ISteamUserAuth/AuthenticateUserTicket` needs one; OpenID needs no key at all, and the assertion
 * is verified against Steam server-side here, so the SteamID64 it yields is trustworthy. Ownership
 * then comes from Steam's public web API with an ordinary (free) user key.
 *
 * Nothing in this module trusts the browser beyond the signed assertion Steam issued, and the
 * assertion is only accepted after Steam itself confirms it (`check_authentication`).
 */

const STEAM_OPENID_ENDPOINT = 'https://steamcommunity.com/openid/login';

/** Steam only ever issues claimed ids in this shape. */
const CLAIMED_ID_PATTERN = /^https:\/\/steamcommunity\.com\/openid\/id\/(\d{17,20})$/;

/** Ravenswatch on Steam. */
export const RAVENSWATCH_APP_ID = 2071280;

export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

/**
 * The URL to send the browser to. `returnTo` must be the same absolute URL that
 * {@link verifySteamOpenIdResponse} is given, because Steam signs it and we compare it: that is
 * what stops an assertion minted for another site being replayed at ours.
 */
export function buildSteamOpenIdRedirect(returnTo: string, realm: string): string {
  const params = new URLSearchParams({
    'openid.ns': 'http://specs.openid.net/auth/2.0',
    'openid.mode': 'checkid_setup',
    'openid.return_to': returnTo,
    'openid.realm': realm,
    'openid.identity': 'http://specs.openid.net/auth/2.0/identifier_select',
    'openid.claimed_id': 'http://specs.openid.net/auth/2.0/identifier_select',
  });
  return `${STEAM_OPENID_ENDPOINT}?${params.toString()}`;
}

export interface VerifyOpenIdOptions {
  /** The exact `openid.return_to` we sent. A mismatch is a replay and is refused. */
  expectedReturnTo: string;
  fetchImpl?: FetchLike;
}

export interface OpenIdResult {
  steamId: string | null;
  /** Why it failed, for logs. Never shown to the browser: it tells a forger which check failed. */
  error?: string;
}

/**
 * Verifies the `openid.*` parameters Steam redirected back with, and returns the SteamID64.
 *
 * The signature is not checked locally — OpenID 2.0's `check_authentication` asks the provider to
 * confirm its own assertion, which is the only way to validate it without an association. So every
 * local check below is a precondition, and Steam's `is_valid:true` is the proof.
 */
export async function verifySteamOpenIdResponse(
  params: URLSearchParams,
  options: VerifyOpenIdOptions,
): Promise<OpenIdResult> {
  const fetchImpl = options.fetchImpl ?? fetch;

  if (params.get('openid.mode') !== 'id_res') {
    return { steamId: null, error: `unexpected openid.mode: ${params.get('openid.mode')}` };
  }

  // Steam is the only provider we accept; a different op_endpoint means a different (hostile) one.
  const opEndpoint = params.get('openid.op_endpoint');
  if (opEndpoint !== STEAM_OPENID_ENDPOINT) {
    return { steamId: null, error: `unexpected openid.op_endpoint: ${opEndpoint}` };
  }

  // Steam signs return_to. Comparing it is what binds the assertion to this site.
  const returnTo = params.get('openid.return_to');
  if (returnTo !== options.expectedReturnTo) {
    return { steamId: null, error: 'openid.return_to does not match the request' };
  }

  const claimedId = params.get('openid.claimed_id');
  const steamId = (claimedId ? CLAIMED_ID_PATTERN.exec(claimedId) : null)?.[1];
  if (!steamId) {
    return { steamId: null, error: `unusable openid.claimed_id: ${claimedId}` };
  }

  // claimed_id and identity must agree, or a forger could have us read the id from the unsigned one.
  if (params.get('openid.identity') !== claimedId) {
    return { steamId: null, error: 'openid.identity does not match openid.claimed_id' };
  }

  // The signed field list has to cover the fields we just relied on; otherwise they are unsigned
  // and Steam's is_valid says nothing about them.
  const signed = (params.get('openid.sig') ? params.get('openid.signed') : null)?.split(',') ?? [];
  for (const required of ['claimed_id', 'identity', 'return_to', 'op_endpoint']) {
    if (!signed.includes(required)) {
      return { steamId: null, error: `openid.signed does not cover ${required}` };
    }
  }

  // Only openid.* params are forwarded, verbatim, with mode swapped to check_authentication.
  const body = new URLSearchParams();
  for (const [key, value] of params) {
    if (key.startsWith('openid.')) {
      body.set(key, value);
    }
  }
  body.set('openid.mode', 'check_authentication');

  let text: string;
  try {
    const response = await fetchImpl(STEAM_OPENID_ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
    if (!response.ok) {
      return { steamId: null, error: `steam check_authentication returned ${response.status}` };
    }
    text = await response.text();
  } catch (err) {
    return { steamId: null, error: `steam check_authentication failed: ${String(err)}` };
  }

  // Key-value form response. Match the whole line: a substring test would accept
  // "is_valid:false" inside some other field.
  const valid = text.split('\n').some((line) => line.trim() === 'is_valid:true');
  if (!valid) {
    return { steamId: null, error: 'steam did not validate the assertion' };
  }

  return { steamId };
}

/**
 * Whether a SteamID64 owns an app, via Steam's public web API with an ordinary (free) key.
 *
 * @returns true/false, or **null for "could not tell"** — which is the common case, not the edge
 * case: `GetOwnedGames` is gated on the profile's *game details* privacy and a private profile
 * returns an empty response indistinguishable from owning nothing. Callers must treat null as
 * unknown and never as "does not own", or private-profile buyers get locked out.
 */
export async function fetchOwnsApp(
  webApiKey: string,
  steamId: string,
  appId: number = RAVENSWATCH_APP_ID,
  fetchImpl: FetchLike = fetch,
): Promise<boolean | null> {
  if (!webApiKey) {
    return null;
  }

  const url = new URL('https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/');
  url.searchParams.set('key', webApiKey);
  url.searchParams.set('steamid', steamId);
  url.searchParams.set('appids_filter[0]', String(appId));
  url.searchParams.set('include_appinfo', '0');
  url.searchParams.set('include_played_free_games', '1');

  try {
    const response = await fetchImpl(url.toString());
    if (!response.ok) {
      return null;
    }
    const body = (await response.json()) as {
      response?: { games?: { appid?: number }[]; game_count?: number };
    };
    const games = body.response?.games;
    // No `games` key at all is a hidden library, not an empty one.
    if (!Array.isArray(games)) {
      return null;
    }
    return games.some((game) => game.appid === appId);
  } catch {
    return null;
  }
}
