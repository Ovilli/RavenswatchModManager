import { describe, expect, it, vi } from 'vitest';
import {
  RAVENSWATCH_APP_ID,
  buildSteamOpenIdRedirect,
  fetchOwnsApp,
  verifySteamOpenIdResponse,
} from '../src/steam-openid.js';

const RETURN_TO = 'https://api.rsmm.me/api/steam-auth/callback';
const STEAM_ID = '76561197960287930';
const ENDPOINT = 'https://steamcommunity.com/openid/login';

/** A well-formed assertion. Individual tests break one field at a time. */
function assertion(overrides: Record<string, string | null> = {}): URLSearchParams {
  const base: Record<string, string> = {
    'openid.ns': 'http://specs.openid.net/auth/2.0',
    'openid.mode': 'id_res',
    'openid.op_endpoint': ENDPOINT,
    'openid.claimed_id': `https://steamcommunity.com/openid/id/${STEAM_ID}`,
    'openid.identity': `https://steamcommunity.com/openid/id/${STEAM_ID}`,
    'openid.return_to': RETURN_TO,
    'openid.response_nonce': '2026-10-04T09:00:00Zabcd',
    'openid.assoc_handle': '1234567890',
    'openid.signed': 'signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle',
    'openid.sig': 'Zm9ydGhlc2lnbmF0dXJl',
  };
  const params = new URLSearchParams(base);
  for (const [key, value] of Object.entries(overrides)) {
    if (value === null) params.delete(key);
    else params.set(key, value);
  }
  return params;
}

const steamSays = (text: string, ok = true): typeof fetch =>
  vi.fn(async () => new Response(text, { status: ok ? 200 : 500 })) as unknown as typeof fetch;

const verify = (
  params: URLSearchParams,
  fetchImpl: typeof fetch = steamSays('ns:...\nis_valid:true\n'),
) => verifySteamOpenIdResponse(params, { expectedReturnTo: RETURN_TO, fetchImpl });

describe('buildSteamOpenIdRedirect', () => {
  it('points at Steam and asks it to select the identity', () => {
    const url = new URL(buildSteamOpenIdRedirect(RETURN_TO, 'https://api.rsmm.me'));

    expect(url.origin + url.pathname).toBe(ENDPOINT);
    expect(url.searchParams.get('openid.mode')).toBe('checkid_setup');
    expect(url.searchParams.get('openid.return_to')).toBe(RETURN_TO);
    expect(url.searchParams.get('openid.realm')).toBe('https://api.rsmm.me');
    expect(url.searchParams.get('openid.claimed_id')).toBe(
      'http://specs.openid.net/auth/2.0/identifier_select',
    );
  });
});

describe('verifySteamOpenIdResponse', () => {
  it('returns the SteamID64 once Steam validates the assertion', async () => {
    const result = await verify(assertion());

    expect(result.steamId).toBe(STEAM_ID);
    expect(result.error).toBeUndefined();
  });

  it('asks Steam to check its own assertion, forwarding only openid params', async () => {
    const fetchImpl = steamSays('is_valid:true');
    const params = assertion();
    params.set('unrelated', 'should-not-be-forwarded');

    await verify(params, fetchImpl);

    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(ENDPOINT);
    expect(init.method).toBe('POST');
    const sent = new URLSearchParams(init.body as string);
    expect(sent.get('openid.mode')).toBe('check_authentication');
    expect(sent.get('openid.sig')).toBe('Zm9ydGhlc2lnbmF0dXJl');
    expect(sent.has('unrelated')).toBe(false);
  });

  it('refuses an assertion Steam does not validate', async () => {
    const result = await verify(assertion(), steamSays('ns:...\nis_valid:false\n'));

    expect(result.steamId).toBeNull();
    expect(result.error).toMatch(/did not validate/);
  });

  it('does not accept is_valid:false embedded in another field', async () => {
    // A substring test for "is_valid:true" would pass on a response that never says it on its own
    // line; this is the reason the check is line-exact.
    const result = await verify(
      assertion(),
      steamSays('note:is_valid:true is not asserted\nis_valid:false\n'),
    );

    expect(result.steamId).toBeNull();
  });

  it('refuses when Steam cannot be reached', async () => {
    const result = await verify(
      assertion(),
      vi.fn(async () => {
        throw new Error('network down');
      }) as unknown as typeof fetch,
    );

    expect(result.steamId).toBeNull();
    expect(result.error).toMatch(/check_authentication failed/);
  });

  it('refuses when Steam answers with an error status', async () => {
    const result = await verify(assertion(), steamSays('', false));

    expect(result.steamId).toBeNull();
    expect(result.error).toMatch(/returned 500/);
  });

  it('refuses a return_to that is not the one we sent', async () => {
    // An assertion minted for another site, replayed here, differs exactly here.
    const result = await verify(assertion({ 'openid.return_to': 'https://evil.example/callback' }));

    expect(result.steamId).toBeNull();
    expect(result.error).toMatch(/return_to/);
  });

  it('refuses a provider that is not Steam', async () => {
    const result = await verify(
      assertion({ 'openid.op_endpoint': 'https://evil.example/openid/login' }),
    );

    expect(result.steamId).toBeNull();
    expect(result.error).toMatch(/op_endpoint/);
  });

  it.each(['cancel', 'checkid_setup', 'setup_needed', ''])(
    'refuses openid.mode %j',
    async (mode) => {
      const result = await verify(assertion({ 'openid.mode': mode }));

      expect(result.steamId).toBeNull();
      expect(result.error).toMatch(/openid\.mode/);
    },
  );

  it.each([
    'https://steamcommunity.com/openid/id/notanumber',
    'https://evil.example/openid/id/76561197960287930',
    'http://steamcommunity.com/openid/id/76561197960287930',
    'https://steamcommunity.com/openid/id/123',
  ])('refuses the claimed_id %j', async (claimedId) => {
    const result = await verify(
      assertion({ 'openid.claimed_id': claimedId, 'openid.identity': claimedId }),
    );

    expect(result.steamId).toBeNull();
    expect(result.error).toMatch(/claimed_id/);
  });

  it('refuses when identity and claimed_id disagree', async () => {
    const result = await verify(
      assertion({ 'openid.identity': 'https://steamcommunity.com/openid/id/76561197960287931' }),
    );

    expect(result.steamId).toBeNull();
    expect(result.error).toMatch(/identity/);
  });

  it.each(['claimed_id', 'identity', 'return_to', 'op_endpoint'])(
    'refuses when %s is not in the signed field list',
    async (field) => {
      const signed = 'signed,op_endpoint,claimed_id,identity,return_to'
        .split(',')
        .filter((f) => f !== field)
        .join(',');

      const result = await verify(assertion({ 'openid.signed': signed }));

      expect(result.steamId).toBeNull();
      expect(result.error).toMatch(new RegExp(field));
    },
  );

  it('refuses when there is no signature at all', async () => {
    const result = await verify(assertion({ 'openid.sig': null }));

    expect(result.steamId).toBeNull();
  });
});

describe('fetchOwnsApp', () => {
  const owned = (appIds: number[]) =>
    vi.fn(
      async () =>
        new Response(JSON.stringify({ response: { games: appIds.map((appid) => ({ appid })) } }), {
          status: 200,
        }),
    ) as unknown as typeof fetch;

  it('reports ownership when the filtered library contains the app', async () => {
    expect(
      await fetchOwnsApp('key', STEAM_ID, RAVENSWATCH_APP_ID, owned([RAVENSWATCH_APP_ID])),
    ).toBe(true);
  });

  it('reports not-owned when the library is visible and does not contain the app', async () => {
    expect(await fetchOwnsApp('key', STEAM_ID, RAVENSWATCH_APP_ID, owned([]))).toBe(false);
  });

  it('sends the key, the steam id and the app filter', async () => {
    const fetchImpl = owned([RAVENSWATCH_APP_ID]);

    await fetchOwnsApp('the-key', STEAM_ID, RAVENSWATCH_APP_ID, fetchImpl);

    const url = new URL((fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(url.searchParams.get('key')).toBe('the-key');
    expect(url.searchParams.get('steamid')).toBe(STEAM_ID);
    expect(url.searchParams.get('appids_filter[0]')).toBe(String(RAVENSWATCH_APP_ID));
  });

  it('answers unknown, not false, when the profile hides its library', async () => {
    // The private-profile case: Steam returns `{"response":{}}`. Reading that as "does not own"
    // would lock out every buyer with a private profile, which is why null exists.
    const hidden = vi.fn(
      async () => new Response(JSON.stringify({ response: {} }), { status: 200 }),
    ) as unknown as typeof fetch;

    expect(await fetchOwnsApp('key', STEAM_ID, RAVENSWATCH_APP_ID, hidden)).toBeNull();
  });

  it('answers unknown with no web api key configured', async () => {
    const never = vi.fn() as unknown as typeof fetch;

    expect(await fetchOwnsApp('', STEAM_ID, RAVENSWATCH_APP_ID, never)).toBeNull();
    expect(never).not.toHaveBeenCalled();
  });

  it.each([
    ['an error status', vi.fn(async () => new Response('', { status: 403 }))],
    ['unreadable json', vi.fn(async () => new Response('not json', { status: 200 }))],
    [
      'a network failure',
      vi.fn(async () => {
        throw new Error('network down');
      }),
    ],
  ])('answers unknown on %s', async (_label, fetchImpl) => {
    expect(
      await fetchOwnsApp('key', STEAM_ID, RAVENSWATCH_APP_ID, fetchImpl as unknown as typeof fetch),
    ).toBeNull();
  });
});
