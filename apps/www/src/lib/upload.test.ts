import { describe, expect, it } from 'vitest';
import { fmtBytes, hexToBase64 } from './upload';

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
