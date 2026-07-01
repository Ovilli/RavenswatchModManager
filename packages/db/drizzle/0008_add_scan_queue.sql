ALTER TABLE "mod_versions" ADD COLUMN "scan_queued_at" timestamp with time zone;--> statement-breakpoint
-- Index the drain query: fetch the oldest queued row cheaply.
CREATE INDEX IF NOT EXISTS "mod_versions_scan_queue_idx"
  ON "mod_versions" ("scan_status", "scan_queued_at");
