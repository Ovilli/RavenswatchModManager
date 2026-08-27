import { describe, expect, it } from 'vitest';
import { buildLogReport, clampReport, redactLogText } from './log-share';

describe('redactLogText', () => {
  it('blanks the account name out of Windows paths but keeps the path shape', () => {
    const out = redactLogText(String.raw`loading C:\Users\alice.smith\Games\mods\_log.txt`);
    expect(out).toBe(String.raw`loading C:\Users\<user>\Games\mods\_log.txt`);
  });

  it('handles forward-slash and bare Users paths', () => {
    expect(redactLogText('C:/Users/bob/x')).toBe('C:/Users/<user>/x');
    expect(redactLogText(String.raw`\Users\bob\x`)).toBe(String.raw`\Users\<user>\x`);
  });

  it('blanks Linux home directories', () => {
    expect(redactLogText('/home/ovilli/.steam/game')).toBe('/home/<user>/.steam/game');
  });

  it('redacts emails, steam ids and player names', () => {
    expect(redactLogText('user a@b.co joined')).toBe('user <email> joined');
    expect(redactLogText('peer 76561198012345678 left')).toBe('peer <steamid> left');
    expect(redactLogText('PlayerName="Alice"')).toBe('PlayerName="<player>"');
    expect(redactLogText('gamertag: Bob')).toBe('gamertag: <player>');
  });

  it('redacts credentials wherever they appear', () => {
    expect(redactLogText('token=abc123 next')).toBe('token=<redacted> next');
    expect(redactLogText('Authorization: Bearer eyJhbGciOi.abc')).toBe(
      'Authorization: Bearer <redacted>',
    );
  });

  it('blanks routable IPs but keeps loopback — a netcode report needs it', () => {
    expect(redactLogText('connect 203.0.113.9:7777')).toBe('connect <ip>:7777');
    expect(redactLogText('bound 127.0.0.1:9000')).toBe('bound 127.0.0.1:9000');
  });

  it('leaves ordinary log lines untouched', () => {
    const line = '[2026-08-27 12:00:00.123 ab12 4242] [va-gate] resolved 191 symbols';
    expect(redactLogText(line)).toBe(line);
  });

  it('blanks anything shaped like a dotted quad, version strings included', () => {
    // Deliberate: a four-segment version and an IPv4 address are the same
    // token. Blanking a version reads oddly; leaking a peer's address does
    // not read oddly at all, so the ambiguity resolves toward privacy.
    expect(redactLogText('loader 1.2.3.4 ready')).toBe('loader <ip> ready');
  });
});

describe('buildLogReport', () => {
  const base = {
    rsmmVersion: '5.1.3',
    os: 'windows',
    loaderLines: ['[..] boot', String.raw`[..] C:\Users\alice\mods`],
  };

  it('stamps the header with version, os and the redaction state', () => {
    const r = buildLogReport(base);
    expect(r.content).toContain('rsmm: 5.1.3');
    expect(r.content).toContain('os: windows');
    expect(r.content).toContain('redacted: yes');
    expect(r.content).toContain(String.raw`C:\Users\<user>\mods`);
    expect(r.source).toBe('loader');
  });

  it('honours redact:false — the dialog offers it, so it has to actually work', () => {
    const r = buildLogReport({ ...base, redact: false });
    expect(r.content).toContain(String.raw`C:\Users\alice\mods`);
    expect(r.content).toContain('redacted: no');
    expect(r.meta.redacted).toBe(false);
  });

  it('lists mods with their enabled state', () => {
    const mod = (id: string, enabled: boolean) =>
      ({ id, slug: id, name: id, version: '1.0.0', enabled }) as never;
    const r = buildLogReport({ ...base, mods: [mod('b', false), mod('a', true)] });
    expect(r.content).toContain('mods: 1 enabled / 2 installed');
    // Sorted by id so two reports of the same install diff cleanly.
    expect(r.content.indexOf('[on ] a')).toBeLessThan(r.content.indexOf('[off] b'));
    expect(r.meta.enabledMods).toEqual(['a@1.0.0']);
  });

  it('becomes a bundle when the launcher log is included', () => {
    const r = buildLogReport({ ...base, launcherLog: '1700000000 [ERROR] boom' });
    expect(r.source).toBe('bundle');
    expect(r.content).toContain('--- launcher log ---');
  });

  it('includes the reporter note when given', () => {
    const r = buildLogReport({ ...base, note: 'crashes on chapter 2' });
    expect(r.content).toContain('crashes on chapter 2');
  });
});

describe('clampReport', () => {
  it('keeps the header and the NEWEST lines — the crash is at the end', () => {
    const header = 'HEADER';
    const body = Array.from({ length: 500 }, (_, i) => `line ${i}`).join('\n');
    const { content, truncated } = clampReport(`${header}\n${body}`, header, 200);
    expect(truncated).toBe(true);
    expect(content.startsWith('HEADER')).toBe(true);
    expect(content).toContain('line 499');
    expect(content).not.toContain('line 0\n');
    expect(content.length).toBeLessThanOrEqual(200);
  });

  it('passes short reports through untouched', () => {
    const { content, truncated } = clampReport('short', 'short', 200);
    expect(truncated).toBe(false);
    expect(content).toBe('short');
  });
});

describe('buildLogReport triage line', () => {
  const stamp = '[2026-08-27 12:00:00.123 ab12 42]';

  it('surfaces the first flagged error in the header', () => {
    const r = buildLogReport({
      rsmmVersion: '5.1.3',
      os: 'windows',
      loaderLines: [
        `${stamp} [va-gate] quiet`,
        `${stamp} [err] [ui-hook] resolve failed`,
        `${stamp} [warn] odd`,
      ],
    });
    expect(r.content).toContain('flagged: 1 error(s), 1 warning(s)');
    expect(r.content).toContain('first error: ');
    expect(r.content).toContain('resolve failed');
    expect(r.meta.errors).toBe(1);
    expect(r.meta.warnings).toBe(1);
  });

  it('says nothing when the loader flagged nothing', () => {
    const r = buildLogReport({
      rsmmVersion: '5.1.3',
      os: 'windows',
      loaderLines: [`${stamp} [va-gate] quiet`],
    });
    expect(r.content).not.toContain('flagged:');
  });

  it('redacts the triage line like everything else', () => {
    const r = buildLogReport({
      rsmmVersion: '5.1.3',
      os: 'windows',
      loaderLines: [`${stamp} [err] cannot open C:\\Users\\alice\\mods`],
    });
    expect(r.content).toContain('C:\\Users\\<user>\\mods');
    expect(r.content).not.toContain('alice');
  });
});
