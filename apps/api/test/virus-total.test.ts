import { afterEach, describe, expect, it, vi } from 'vitest';

// src/env.ts throws without DATABASE_URL (absent in CI); the client only needs the key.
vi.mock('../src/env.js', () => ({ env: { virusTotalApiKey: 'test-key' } }));

import {
  VirusTotalAlreadySubmittedError,
  getVirusTotalFileReport,
  submitVirusTotalFile,
} from '../src/virus-total.js';

function reply(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('VirusTotal client', () => {
  it('maps a 409 AlreadySubmittedError upload to its own error, not a scan failure', async () => {
    vi.stubGlobal(
      'fetch',
      reply(409, {
        error: { code: 'AlreadySubmittedError', message: 'Already being submitted for scanning' },
      }),
    );
    await expect(submitVirusTotalFile(new Uint8Array([1, 2, 3]), 'm.zip')).rejects.toBeInstanceOf(
      VirusTotalAlreadySubmittedError,
    );
  });

  it('reads a finished file report by hash', async () => {
    vi.stubGlobal(
      'fetch',
      reply(200, {
        data: {
          attributes: {
            last_analysis_date: 1_757_750_000,
            last_analysis_stats: { harmless: 0, malicious: 0, suspicious: 0, undetected: 62 },
          },
        },
      }),
    );
    const report = await getVirusTotalFileReport('a'.repeat(64));
    expect(report?.status).toBe('completed');
    expect(report?.stats.undetected).toBe(62);
  });

  it('reports a file with no finished analysis as not completed', async () => {
    vi.stubGlobal('fetch', reply(200, { data: { attributes: {} } }));
    expect((await getVirusTotalFileReport('a'.repeat(64)))?.status).toBe('queued');
  });

  it('returns null for a file VirusTotal has no report for', async () => {
    vi.stubGlobal('fetch', reply(404, { error: { code: 'NotFoundError' } }));
    expect(await getVirusTotalFileReport('a'.repeat(64))).toBeNull();
  });
});
