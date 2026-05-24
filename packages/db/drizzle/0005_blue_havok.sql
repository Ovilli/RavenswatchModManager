CREATE TABLE "collection_reviews" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"collection_id" uuid NOT NULL,
	"user_id" text NOT NULL,
	"rating" integer NOT NULL,
	"title" varchar(120),
	"body" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "collections" ADD COLUMN "description" text;--> statement-breakpoint
ALTER TABLE "collections" ADD COLUMN "image_url" text;--> statement-breakpoint
ALTER TABLE "collections" ADD COLUMN "screenshots" jsonb;--> statement-breakpoint
ALTER TABLE "collection_reviews" ADD CONSTRAINT "collection_reviews_collection_id_collections_id_fk" FOREIGN KEY ("collection_id") REFERENCES "public"."collections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "collection_reviews" ADD CONSTRAINT "collection_reviews_user_id_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "collection_reviews_collection_user_idx" ON "collection_reviews" USING btree ("collection_id","user_id");--> statement-breakpoint
CREATE INDEX "collection_reviews_collection_idx" ON "collection_reviews" USING btree ("collection_id");