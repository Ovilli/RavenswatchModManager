import { describe, expect, it } from 'vitest';
import {
  DEFAULT_TICKET_TTL_SECONDS,
  TICKET_PREFIX,
  mintSteamTicket,
  signPayload,
} from '../src/steam-ticket.js';

/**
 * The cross-language contract. `services/stormancer/tests/TicketVectorTests.cs` holds the same
 * key, payload and ticket; if these two drift, the backend refuses every login this API mints.
 */
const VECTOR_KEY = 'rsmm-vector-key';
const VECTOR_PAYLOAD =
  '{"sid":"76561197960287930","own":true,"pack":"a1b2c3d4e5f60718","packName":"Vector pack","iat":1760000000,"exp":1760000300,"jti":"vector-0001"}';
const VECTOR_TICKET =
  'rsmm1.eyJzaWQiOiI3NjU2MTE5Nzk2MDI4NzkzMCIsIm93biI6dHJ1ZSwicGFjayI6ImExYjJjM2Q0ZTVmNjA3MTgi' +
  'LCJwYWNrTmFtZSI6IlZlY3RvciBwYWNrIiwiaWF0IjoxNzYwMDAwMDAwLCJleHAiOjE3NjAwMDAzMDAsImp0aSI6In' +
  'ZlY3Rvci0wMDAxIn0.h4lMbeKjFx-c5m7tRCpnWtIeNvT5yAA64LD1r5zLY-M';

const STEAM_ID = '76561197960287930';
const decodePayload = (ticket: string) =>
  JSON.parse(Buffer.from(ticket.split('.')[1], 'base64url').toString('utf8'));

describe('steam ticket format vector', () => {
  it('signs the vector payload byte for byte', () => {
    expect(signPayload(VECTOR_KEY, VECTOR_PAYLOAD)).toBe(VECTOR_TICKET);
  });

  it('mints the vector ticket from its claims, so key order is part of the format', () => {
    const ticket = mintSteamTicket(
      VECTOR_KEY,
      {
        steamId: STEAM_ID,
        ownsGame: true,
        pack: 'a1b2c3d4e5f60718',
        packName: 'Vector pack',
      },
      { now: 1760000000, ttlSeconds: 300, jti: 'vector-0001' },
    );

    expect(ticket).toBe(VECTOR_TICKET);
  });
});

describe('mintSteamTicket', () => {
  const claims = { steamId: STEAM_ID, ownsGame: true, pack: 'abc', packName: 'Pack' };

  it('produces three base64url parts behind the version prefix', () => {
    const parts = mintSteamTicket('k', claims).split('.');

    expect(parts).toHaveLength(3);
    expect(parts[0]).toBe(TICKET_PREFIX);
    // base64url: no +, / or = anywhere, or the C# decoder rejects it.
    expect(parts[1]).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(parts[2]).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it('defaults the validity window to the shared ttl', () => {
    const payload = decodePayload(mintSteamTicket('k', claims, { now: 1000 }));

    expect(payload.iat).toBe(1000);
    expect(payload.exp).toBe(1000 + DEFAULT_TICKET_TTL_SECONDS);
  });

  it('gives every ticket a distinct id so the backend can refuse a replay', () => {
    const first = decodePayload(mintSteamTicket('k', claims));
    const second = decodePayload(mintSteamTicket('k', claims));

    expect(first.jti).not.toBe(second.jti);
  });

  it('normalises a blank pack to null so unmodded players match each other', () => {
    const payload = decodePayload(mintSteamTicket('k', { ...claims, pack: '   ', packName: '' }));

    expect(payload.pack).toBeNull();
    expect(payload.packName).toBeNull();
  });

  it('keeps a null pack as null', () => {
    const payload = decodePayload(mintSteamTicket('k', { ...claims, pack: null, packName: null }));

    expect(payload.pack).toBeNull();
    expect(payload.packName).toBeNull();
  });

  it('carries the ownership flag through unchanged', () => {
    expect(decodePayload(mintSteamTicket('k', { ...claims, ownsGame: false })).own).toBe(false);
    expect(decodePayload(mintSteamTicket('k', { ...claims, ownsGame: true })).own).toBe(true);
  });

  it('changes the signature when any claim changes', () => {
    const base = mintSteamTicket('k', claims, { now: 1000, jti: 'j' });
    const other = mintSteamTicket('k', { ...claims, pack: 'different' }, { now: 1000, jti: 'j' });

    expect(other).not.toBe(base);
  });

  it('changes the signature when the key changes', () => {
    const a = mintSteamTicket('key-a', claims, { now: 1000, jti: 'j' });
    const b = mintSteamTicket('key-b', claims, { now: 1000, jti: 'j' });

    expect(a).not.toBe(b);
  });

  it('refuses to mint without a signing key', () => {
    // A missing secret must not produce a ticket signed with the empty string: the grid would
    // reject it anyway, but minting it at all hides a misconfiguration behind a login failure.
    expect(() => mintSteamTicket('', claims)).toThrow(/no signing key/);
  });

  it.each(['', 'not-a-number', '7656119796028793', '76561197960265727', '-1'])(
    'refuses to mint for %j, which is not a SteamID64',
    (steamId) => {
      expect(() => mintSteamTicket('k', { ...claims, steamId })).toThrow(/SteamID64/);
    },
  );

  it('accepts the lowest valid SteamID64', () => {
    expect(() => mintSteamTicket('k', { ...claims, steamId: '76561197960265728' })).not.toThrow();
  });

  it.each([0, -1, 1.5, Number.NaN])('refuses a ttl of %j', (ttlSeconds) => {
    expect(() => mintSteamTicket('k', claims, { ttlSeconds })).toThrow(/ttl/);
  });
});
