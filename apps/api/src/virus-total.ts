import { env } from './env.js';

export interface VirusTotalAnalysis {
  analysisId: string;
  permalink: string;
}

/** Per-engine tally VirusTotal reports for a URL/file analysis. */
export interface VirusTotalStats {
  malicious: number;
  suspicious: number;
  harmless: number;
  undetected: number;
}

export interface VirusTotalVerdict {
  /** 'completed' once every engine has reported; 'queued'/'in-progress' otherwise. */
  status: string;
  stats: VirusTotalStats;
}

/**
 * Thrown when VirusTotal answers 429. The caller uses this to stop polling
 * gracefully (free-tier is 4 lookups/min) instead of treating it as a scan
 * failure — a rate-limited poll just means "verdict not known yet".
 */
export class VirusTotalRateLimitError extends Error {
  constructor(body: string) {
    super(`VirusTotal rate limited (429): ${body}`.trim());
    this.name = 'VirusTotalRateLimitError';
  }
}

function normalizeStats(raw: unknown): VirusTotalStats {
  const s = (raw ?? {}) as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
  return {
    malicious: num(s.malicious),
    suspicious: num(s.suspicious),
    harmless: num(s.harmless),
    undetected: num(s.undetected),
  };
}

/**
 * Largest file the public/free VirusTotal API accepts on the simple
 * `/api/v3/files` endpoint. Anything bigger needs the large-file upload_url
 * dance (premium-ish); we fall back to URL-scan for those instead.
 */
export const MAX_VT_FILE_BYTES = 32 * 1024 * 1024;

/**
 * Upload the actual bytes for a full file analysis. Stronger than URL-scan:
 * VT runs every AV engine on the exact archive we hold, and (VT unpacks
 * archives) on its members. Only viable up to MAX_VT_FILE_BYTES.
 */
export async function submitVirusTotalFile(
  bytes: Buffer,
  filename: string,
): Promise<VirusTotalAnalysis> {
  const form = new FormData();
  form.append('file', new Blob([bytes], { type: 'application/zip' }), filename);

  const response = await fetch('https://www.virustotal.com/api/v3/files', {
    method: 'POST',
    headers: { 'x-apikey': env.virusTotalApiKey },
    body: form,
  });

  const bodyText = await response.text();
  if (response.status === 429) throw new VirusTotalRateLimitError(bodyText);
  if (!response.ok) {
    throw new Error(`VirusTotal file upload failed (${response.status}): ${bodyText}`.trim());
  }

  const json = (bodyText ? JSON.parse(bodyText) : null) as {
    data?: { id?: string; links?: { self?: string } };
  } | null;
  const analysisId = json?.data?.id;
  if (!analysisId) {
    throw new Error('VirusTotal file response did not include an analysis id');
  }
  return {
    analysisId,
    permalink:
      json.data?.links?.self ??
      `https://www.virustotal.com/gui/file-analysis/${encodeURIComponent(analysisId)}`,
  };
}

export async function submitVirusTotalUrl(url: string): Promise<VirusTotalAnalysis> {
  const response = await fetch('https://www.virustotal.com/api/v3/urls', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'x-apikey': env.virusTotalApiKey,
    },
    body: new URLSearchParams({ url }),
  });

  const bodyText = await response.text();

  if (!response.ok) {
    throw new Error(`VirusTotal scan request failed (${response.status}): ${bodyText}`.trim());
  }

  const json = (bodyText ? JSON.parse(bodyText) : null) as {
    data?: {
      id?: string;
      links?: {
        self?: string;
      };
    };
  } | null;

  const analysisId = json?.data?.id;
  if (!analysisId) {
    throw new Error('VirusTotal response did not include an analysis id');
  }

  return {
    analysisId,
    permalink:
      json.data?.links?.self ??
      `https://www.virustotal.com/gui/url/${encodeURIComponent(analysisId)}/detection`,
  };
}

/**
 * Read the current state of a submitted analysis. Note that `stats` is
 * populated incrementally: a `malicious` count can appear while `status` is
 * still 'in-progress', which is enough to flag early.
 */
export async function getVirusTotalAnalysis(analysisId: string): Promise<VirusTotalVerdict> {
  const response = await fetch(
    `https://www.virustotal.com/api/v3/analyses/${encodeURIComponent(analysisId)}`,
    { headers: { 'x-apikey': env.virusTotalApiKey } },
  );

  const bodyText = await response.text();
  if (response.status === 429) throw new VirusTotalRateLimitError(bodyText);
  if (!response.ok) {
    throw new Error(`VirusTotal analysis fetch failed (${response.status}): ${bodyText}`.trim());
  }

  const json = (bodyText ? JSON.parse(bodyText) : null) as {
    data?: { attributes?: { status?: string; stats?: unknown } };
  } | null;
  const attrs = json?.data?.attributes ?? {};
  return { status: attrs.status ?? 'unknown', stats: normalizeStats(attrs.stats) };
}
