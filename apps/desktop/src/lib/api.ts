import { createApiClient } from '@rsmm/api-client';
import { getApiUrl } from './api-url';

export const api = createApiClient({
  baseUrl: getApiUrl(),
});
