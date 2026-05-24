import { createApiClient } from '@rsmm/api-client';
import { getApiUrl } from './api-url';

const API_BASE = getApiUrl();

export const api = createApiClient({
  baseUrl: API_BASE,
});

export function getApiBaseUrl(): string {
  return API_BASE;
}
