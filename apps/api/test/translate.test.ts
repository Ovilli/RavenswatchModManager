import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  GatewayUnavailable,
  type Listing,
  alreadyChinese,
  freshTranslation,
  linksIn,
  sourceHash,
  translateListing,
  translationsConfigured,
  validateTranslation,
} from '../src/translate.js';

const listing: Listing = {
  name: 'Damage Meter',
  summary: 'Shows who dealt how much damage.',
  description: 'See [the guide](https://docs.rsmm.me/guide) for setup.',
};

function gateway(status: number, content?: string): typeof fetch {
  return vi.fn(
    async () =>
      new Response(
        JSON.stringify({ model: 'alibaba/qwen3.7-flash', choices: [{ message: { content } }] }),
        { status },
      ),
  ) as unknown as typeof fetch;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('validateTranslation', () => {
  it('accepts a faithful translation that keeps the original link', () => {
    const r = validateTranslation(listing, {
      name: '伤害统计',
      summary: '显示每个人造成了多少伤害。',
      description: '设置方法请见[指南](https://docs.rsmm.me/guide)。',
    });
    expect(r.ok).toBe(true);
  });

  it('refuses a translation that adds a link the original lacks', () => {
    const r = validateTranslation(listing, {
      name: '伤害统计',
      summary: '显示伤害。',
      description: '请下载[这里](https://evil.example/x.exe)。',
    });
    expect(r).toMatchObject({ ok: false, reason: expect.stringContaining('evil.example') });
  });

  it('refuses a translation that drops a field the original has', () => {
    const r = validateTranslation(listing, { name: '伤害统计', summary: '', description: '指南' });
    expect(r).toMatchObject({ ok: false, reason: 'missing summary' });
  });

  it('refuses an answer that balloons far past the original', () => {
    const r = validateTranslation(listing, {
      name: '伤'.repeat(500),
      summary: '显示伤害。',
      description: '[指南](https://docs.rsmm.me/guide)',
    });
    expect(r).toMatchObject({ ok: false, reason: expect.stringContaining('name') });
  });

  it('keeps fields null where the original has none', () => {
    const r = validateTranslation(
      { name: 'X', summary: null, description: null },
      { name: '某', summary: 'injected text', description: 'more' },
    );
    expect(r).toEqual({ ok: true, value: { name: '某', summary: null, description: null } });
  });
});

describe('helpers', () => {
  it('finds markdown and bare links', () => {
    expect([...linksIn('a [b](https://x.dev/y) and https://z.dev/w.')].sort()).toEqual([
      'https://x.dev/y',
      'https://z.dev/w',
    ]);
  });

  it('spots a listing already written in Chinese', () => {
    expect(alreadyChinese({ name: '伤害统计', summary: '显示伤害', description: null })).toBe(true);
    expect(alreadyChinese(listing)).toBe(false);
  });

  it('serves a stored translation only while the original is unchanged', () => {
    const row = {
      sourceHash: sourceHash(listing),
      translatedAt: new Date(),
      name: '伤害统计',
      summary: '显示伤害。',
      description: '指南',
    };
    expect(freshTranslation(listing, row)?.name).toBe('伤害统计');
    expect(freshTranslation({ ...listing, summary: 'Edited.' }, row)).toBeNull();
    expect(freshTranslation(listing, { ...row, translatedAt: null })).toBeNull();
    // "already in this language" rows carry no text and are never served
    expect(
      freshTranslation(listing, { ...row, name: null, summary: null, description: null }),
    ).toBeNull();
  });
});

describe('translateListing', () => {
  it('is off without a gateway credential', () => {
    vi.stubEnv('AI_GATEWAY_API_KEY', '');
    vi.stubEnv('VERCEL_OIDC_TOKEN', '');
    expect(translationsConfigured()).toBe(false);
  });

  it('returns the checked translation, tolerating a fenced JSON answer', async () => {
    vi.stubEnv('AI_GATEWAY_API_KEY', 'test-key');
    const answer = JSON.stringify({
      name: '伤害统计',
      summary: '显示伤害。',
      description: '[指南](https://docs.rsmm.me/guide)',
    });
    const f = gateway(200, `\`\`\`json\n${answer}\n\`\`\``);
    const r = await translateListing(listing, 'zh-CN', f);
    expect(r.value.name).toBe('伤害统计');
    const [url, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('https://ai-gateway.vercel.sh/v1/chat/completions');
    expect((init as RequestInit).headers).toMatchObject({ Authorization: 'Bearer test-key' });
  });

  it('reports a credit or budget refusal as GatewayUnavailable', async () => {
    vi.stubEnv('AI_GATEWAY_API_KEY', 'test-key');
    await expect(translateListing(listing, 'zh-CN', gateway(402))).rejects.toBeInstanceOf(
      GatewayUnavailable,
    );
  });

  it('rejects an answer that is not JSON', async () => {
    vi.stubEnv('AI_GATEWAY_API_KEY', 'test-key');
    await expect(
      translateListing(listing, 'zh-CN', gateway(200, 'Sure! Here is...')),
    ).rejects.toThrow('not valid JSON');
  });
});
