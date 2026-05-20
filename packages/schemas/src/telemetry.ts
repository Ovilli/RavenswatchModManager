import { z } from 'zod';

export const osSchema = z.enum(['linux', 'windows', 'macos', 'unknown']);

export const telemetryRunSchema = z.object({
  rsmmVersion: z.string().max(32),
  os: osSchema,
  gameBuild: z.string().max(64).optional(),
  ok: z.boolean(),
  durationMs: z.number().int().nonnegative().optional(),
  payload: z.record(z.string(), z.unknown()).optional(),
});

export type TelemetryRun = z.infer<typeof telemetryRunSchema>;

export const crashReportSchema = z.object({
  rsmmVersion: z.string().max(32),
  os: osSchema,
  errorClass: z.string().max(128),
  message: z.string().max(2048),
  stacktrace: z.string().max(32_000),
  context: z.record(z.string(), z.unknown()).optional(),
});

export type CrashReport = z.infer<typeof crashReportSchema>;
