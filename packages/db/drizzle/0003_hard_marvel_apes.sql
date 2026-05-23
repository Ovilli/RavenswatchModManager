-- Convert screenshots text[] -> jsonb [{url, caption?}].
-- Existing URLs migrate as { "url": <url> }; captions get added later.
ALTER TABLE "mods" ADD COLUMN IF NOT EXISTS "screenshots_jsonb" jsonb;--> statement-breakpoint
UPDATE "mods"
   SET "screenshots_jsonb" = (
     SELECT coalesce(jsonb_agg(jsonb_build_object('url', s)), '[]'::jsonb)
     FROM unnest("screenshots") AS s
   )
   WHERE "screenshots" IS NOT NULL;--> statement-breakpoint
ALTER TABLE "mods" DROP COLUMN "screenshots";--> statement-breakpoint
ALTER TABLE "mods" RENAME COLUMN "screenshots_jsonb" TO "screenshots";
