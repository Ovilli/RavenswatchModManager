ALTER TABLE "mod_versions" ADD COLUMN "scan_status" varchar(16) DEFAULT 'pending' NOT NULL;--> statement-breakpoint
ALTER TABLE "mod_versions" ADD COLUMN "scan_id" text;--> statement-breakpoint
ALTER TABLE "mod_versions" ADD COLUMN "scan_stats" jsonb;--> statement-breakpoint
ALTER TABLE "mod_versions" ADD COLUMN "scanned_at" timestamp with time zone;--> statement-breakpoint
-- Existing rows predate scanning; mark them 'skipped' rather than leaving them
-- 'pending' forever. The gate only hides 'flagged', so this is cosmetic, but it
-- keeps status honest for already-published versions.
UPDATE "mod_versions" SET "scan_status" = 'skipped' WHERE "scan_status" = 'pending';
