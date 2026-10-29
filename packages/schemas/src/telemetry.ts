import { z } from 'zod';

export const osSchema = z.enum(['linux', 'windows', 'unknown']);

function recordSizeLimit(maxBytes: number) {
  return (v: Record<string, unknown> | undefined): boolean => {
    if (v === undefined) return true;
    try {
      return new TextEncoder().encode(JSON.stringify(v)).length <= maxBytes;
    } catch {
      return false;
    }
  };
}

export const telemetryRunSchema = z.object({
  rsmmVersion: z.string().max(32),
  os: osSchema,
  gameBuild: z.string().max(64).optional(),
  ok: z.boolean(),
  durationMs: z.number().int().nonnegative().optional(),
  payload: z
    .record(z.string(), z.unknown())
    .optional()
    .refine(
      (v) => v === undefined || Object.keys(v).length <= 50,
      'payload must have at most 50 keys',
    )
    .refine(recordSizeLimit(10_000), 'payload must not exceed 10KB serialized'),
});

export type TelemetryRun = z.infer<typeof telemetryRunSchema>;

/** Daily "this install is alive" ping. `installId` is minted locally and
 * random — it identifies an install, never a person. */
export const installPingSchema = z.object({
  installId: z.string().uuid(),
  rsmmVersion: z.string().max(32),
  os: osSchema,
});

export type InstallPing = z.infer<typeof installPingSchema>;

export const crashReportSchema = z.object({
  rsmmVersion: z.string().max(32),
  os: osSchema,
  errorClass: z.string().max(128),
  message: z.string().max(2048),
  stacktrace: z.string().max(32_000),
  context: z
    .record(z.string(), z.unknown())
    .optional()
    .refine(
      (v) => v === undefined || Object.keys(v).length <= 50,
      'context must have at most 50 keys',
    )
    .refine(recordSizeLimit(10_000), 'context must not exceed 10KB serialized'),
});

export type CrashReport = z.infer<typeof crashReportSchema>;
