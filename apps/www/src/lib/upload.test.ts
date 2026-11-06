import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fmtBytes, hexToBase64, putFile } from './upload';

describe('upload helpers', () => {
  it('turns a hex SHA-256 into the base64 S3 expects', () => {
    // sha256("") — a known vector.
    const hex = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
    expect(hexToBase64(hex)).toBe('47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=');
  });

  it('formats sizes', () => {
    expect(fmtBytes(512)).toBe('512 B');
    expect(fmtBytes(1536)).toBe('1.5 KiB');
    expect(fmtBytes(5 * 1024 * 1024)).toBe('5.0 MiB');
  });
});

class MockXMLHttpRequest {
  status = 0;
  responseText = '';
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  upload = {
    onprogress: null as
      | ((event: Pick<ProgressEvent, 'lengthComputable' | 'loaded' | 'total'>) => void)
      | null,
  };
  open = vi.fn();
  setRequestHeader = vi.fn();
  send = vi.fn();
}

describe('putFile', () => {
  let xhr: MockXMLHttpRequest;
  const file = new Blob(['archive']);
  const url = 'https://storage.example.com/mod.zip';
  const opts = {
    headers: { 'Content-Type': 'application/zip', 'x-amz-checksum-sha256': 'checksum' },
    what: 'mod archive upload',
  };

  beforeEach(() => {
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends MockXMLHttpRequest {
        constructor() {
          super();
          xhr = this;
        }
      },
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it('sends the file and signed headers and reports computable progress', async () => {
    const onProgress = vi.fn();
    const result = putFile(url, file, { ...opts, onProgress });

    expect(xhr.open).toHaveBeenCalledWith('PUT', url);
    for (const [header, value] of Object.entries(opts.headers)) {
      expect(xhr.setRequestHeader).toHaveBeenCalledWith(header, value);
    }
    expect(xhr.send).toHaveBeenCalledWith(file);
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 0, total: 0 });
    expect(onProgress).not.toHaveBeenCalled();
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 3, total: file.size });
    expect(onProgress).toHaveBeenCalledWith(3, file.size);

    xhr.status = 200;
    xhr.onload?.();
    await expect(result).resolves.toBeUndefined();
  });

  it.each(['load', 'error'] as const)(
    'waits for server confirmation after a PUT %s event',
    async (event) => {
      let confirm = () => {};
      const confirmed = new Promise<void>((resolve) => {
        confirm = resolve;
      });
      const confirmUpload = vi.fn(() => confirmed);
      const settled = vi.fn();
      const failed = vi.fn();
      const result = putFile(url, file, { ...opts, confirmUpload });
      const completion = result.then(settled, failed);

      xhr.status = event === 'load' ? 200 : 0;
      if (event === 'load') xhr.onload?.();
      else xhr.onerror?.();

      expect(confirmUpload).toHaveBeenCalledOnce();
      await Promise.resolve();
      expect(settled).not.toHaveBeenCalled();
      confirm();
      await completion;
      expect(settled).toHaveBeenCalledOnce();
      expect(failed).not.toHaveBeenCalled();
      expect(xhr.send).toHaveBeenCalledOnce();
    },
  );

  it.each(['load', 'error'] as const)(
    'propagates a failed server confirmation after a PUT %s event',
    async (event) => {
      const error = new Error('upload not completed');
      const confirmUpload = vi.fn().mockRejectedValue(error);
      const result = putFile(url, file, { ...opts, confirmUpload });
      const rejected = expect(result).rejects.toBe(error);

      xhr.status = event === 'load' ? 200 : 0;
      if (event === 'load') xhr.onload?.();
      else xhr.onerror?.();

      await rejected;
      expect(confirmUpload).toHaveBeenCalledOnce();
      expect(xhr.send).toHaveBeenCalledOnce();
    },
  );

  it('does not treat 100% upload progress as successful confirmation', async () => {
    const onProgress = vi.fn();
    const result = putFile(url, file, { ...opts, onProgress });
    const rejected = expect(result).rejects.toThrow('mod archive upload failed: network error');

    xhr.upload.onprogress?.({ lengthComputable: true, loaded: file.size, total: file.size });
    xhr.onerror?.();

    await rejected;
    expect(onProgress).toHaveBeenCalledWith(file.size, file.size);
  });

  it('rejects if the confirmation callback throws before making a request', async () => {
    const error = new Error('could not confirm upload');
    const result = putFile(url, file, {
      ...opts,
      confirmUpload: () => {
        throw error;
      },
    });
    const rejected = expect(result).rejects.toBe(error);
    xhr.onerror?.();

    await rejected;
  });

  it.each([400, 403, 500])('does not mask an HTTP %i storage rejection', async (status) => {
    const confirmUpload = vi.fn();
    const result = putFile(url, file, { ...opts, confirmUpload });
    const rejected = expect(result).rejects.toThrow(
      `object storage rejected the mod archive upload (${status}). Access denied`,
    );
    xhr.status = status;
    xhr.responseText = '<Error><Code>AccessDenied</Code><Message>Access denied</Message></Error>';
    xhr.onload?.();

    await rejected;
    expect(confirmUpload).not.toHaveBeenCalled();
  });

  it('preserves the storage-full error without attempting confirmation', async () => {
    const confirmUpload = vi.fn();
    const result = putFile(url, file, { ...opts, confirmUpload });
    const rejected = expect(result).rejects.toThrow('object storage is full right now');
    xhr.status = 507;
    xhr.onload?.();

    await rejected;
    expect(confirmUpload).not.toHaveBeenCalled();
  });
});
