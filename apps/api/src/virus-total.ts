import { env } from './env.js';

export interface VirusTotalAnalysis {
  analysisId: string;
  permalink: string;
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

  const json = (bodyText ? JSON.parse(bodyText) : null) as
    | {
        data?: {
          id?: string;
          links?: {
            self?: string;
          };
        };
      }
    | null;

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