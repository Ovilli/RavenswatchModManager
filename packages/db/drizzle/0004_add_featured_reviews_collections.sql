CREATE TABLE "collection_mods" (
	"collection_id" uuid NOT NULL,
	"mod_id" uuid NOT NULL,
	"position" integer DEFAULT 0 NOT NULL,
	"added_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "collection_mods_collection_id_mod_id_pk" PRIMARY KEY("collection_id","mod_id")
);
--> statement-breakpoint
CREATE TABLE "collections" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"slug" varchar(64) NOT NULL,
	"owner_id" text NOT NULL,
	"name" text NOT NULL,
	"summary" text,
	"is_public" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "mod_reviews" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"mod_id" uuid NOT NULL,
	"user_id" text NOT NULL,
	"rating" integer NOT NULL,
	"title" varchar(120),
	"body" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "mods" ADD COLUMN "featured" boolean DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE "mods" ADD COLUMN "featured_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "collection_mods" ADD CONSTRAINT "collection_mods_collection_id_collections_id_fk" FOREIGN KEY ("collection_id") REFERENCES "public"."collections"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "collection_mods" ADD CONSTRAINT "collection_mods_mod_id_mods_id_fk" FOREIGN KEY ("mod_id") REFERENCES "public"."mods"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "collections" ADD CONSTRAINT "collections_owner_id_user_id_fk" FOREIGN KEY ("owner_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mod_reviews" ADD CONSTRAINT "mod_reviews_mod_id_mods_id_fk" FOREIGN KEY ("mod_id") REFERENCES "public"."mods"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mod_reviews" ADD CONSTRAINT "mod_reviews_user_id_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "collection_mods_coll_idx" ON "collection_mods" USING btree ("collection_id");--> statement-breakpoint
CREATE UNIQUE INDEX "collections_slug_idx" ON "collections" USING btree ("slug");--> statement-breakpoint
CREATE INDEX "collections_owner_idx" ON "collections" USING btree ("owner_id");--> statement-breakpoint
CREATE UNIQUE INDEX "mod_reviews_mod_user_idx" ON "mod_reviews" USING btree ("mod_id","user_id");--> statement-breakpoint
CREATE INDEX "mod_reviews_mod_idx" ON "mod_reviews" USING btree ("mod_id");--> statement-breakpoint
CREATE INDEX "mods_featured_idx" ON "mods" USING btree ("featured");