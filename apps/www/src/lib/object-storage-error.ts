function readXmlTag(xml: string, tag: string): string | undefined {
  const re = new RegExp(`<${tag}>([\\s\\S]*?)<\\/\\s*${tag}>`, 'i');
  const match = re.exec(xml);
  const value = match?.[1]?.trim();
  return value || undefined;
}

export function formatObjectStorageError(
  status: number,
  body: string,
  actionLabel = 'upload',
): string {
  const code = readXmlTag(body, 'Code');
  const message = readXmlTag(body, 'Message');

  if (status === 507 || code === 'XMinioStorageFull') {
    return `object storage is full right now; ${actionLabel} cannot complete. Please try again later.`;
  }

  if (message) {
    return `object storage rejected the ${actionLabel} (${status}). ${message}`;
  }

  if (code) {
    return `object storage rejected the ${actionLabel} (${status}). ${code}`;
  }

  return `object storage rejected the ${actionLabel} (${status}).`;
}
