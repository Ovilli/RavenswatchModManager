CREATE TYPE "public"."mod_category" AS ENUM('gameplay', 'balance', 'cosmetic', 'qol', 'audio', 'difficulty', 'speedrun', 'utility');--> statement-breakpoint
CREATE TABLE "account" (
	"id" text PRIMARY KEY NOT NULL,
	"user_id" text NOT NULL,
	"account_id" text NOT NULL,
	"provider_id" text NOT NULL,
	"access_token" text,
	"refresh_token" text,
	"id_token" text,
	"access_token_expires_at" timestamp with time zone,
	"refresh_token_expires_at" timestamp with time zone,
	"scope" text,
	"password" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "session" (
	"id" text PRIMARY KEY NOT NULL,
	"user_id" text NOT NULL,
	"token" text NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"ip_address" text,
	"user_agent" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "session_token_unique" UNIQUE("token")
);
--> statement-breakpoint
CREATE TABLE "user" (
	"id" text PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"email" text NOT NULL,
	"email_verified" boolean DEFAULT false NOT NULL,
	"image" text,
	"handle" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_email_unique" UNIQUE("email"),
	CONSTRAINT "user_handle_unique" UNIQUE("handle")
);
--> statement-breakpoint
CREATE TABLE "verification" (
	"id" text PRIMARY KEY NOT NULL,
	"identifier" text NOT NULL,
	"value" text NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "mod_authors" (
	"mod_id" uuid NOT NULL,
	"user_id" text NOT NULL,
	"role" varchar(16) DEFAULT 'contrib' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "mod_authors_mod_id_user_id_pk" PRIMARY KEY("mod_id","user_id")
);
--> statement-breakpoint
CREATE TABLE "mod_downloads" (
	"mod_id" uuid NOT NULL,
	"version_id" uuid,
	"day" date DEFAULT CURRENT_DATE NOT NULL,
	"count" integer DEFAULT 0 NOT NULL,
	CONSTRAINT "mod_downloads_mod_id_day_pk" PRIMARY KEY("mod_id","day")
);
--> statement-breakpoint
CREATE TABLE "mod_versions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"mod_id" uuid NOT NULL,
	"version" varchar(32) NOT NULL,
	"sha256" varchar(64) NOT NULL,
	"size_bytes" bigint NOT NULL,
	"manifest_json" jsonb NOT NULL,
	"asset_url" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "mods" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"slug" varchar(64) NOT NULL,
	"name" text NOT NULL,
	"summary" text,
	"description" text,
	"license" varchar(64),
	"repo_url" text,
	"homepage_url" text,
	"tags" text[],
	"category" "mod_category",
	"author_name" varchar(128),
	"image_url" text,
	"rating" numeric(3, 2),
	"owner_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "crash_reports" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" text,
	"rsmm_version" varchar(32) NOT NULL,
	"os" varchar(16) NOT NULL,
	"error_class" varchar(128) NOT NULL,
	"message" text NOT NULL,
	"stacktrace" text NOT NULL,
	"context" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "telemetry_runs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" text,
	"rsmm_version" varchar(32) NOT NULL,
	"os" varchar(16) NOT NULL,
	"game_build" varchar(64),
	"ok" boolean NOT NULL,
	"duration_ms" integer,
	"payload" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "account" ADD CONSTRAINT "account_user_id_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "session" ADD CONSTRAINT "session_user_id_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mod_authors" ADD CONSTRAINT "mod_authors_mod_id_mods_id_fk" FOREIGN KEY ("mod_id") REFERENCES "public"."mods"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mod_authors" ADD CONSTRAINT "mod_authors_user_id_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."user"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mod_downloads" ADD CONSTRAINT "mod_downloads_mod_id_mods_id_fk" FOREIGN KEY ("mod_id") REFERENCES "public"."mods"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mod_downloads" ADD CONSTRAINT "mod_downloads_version_id_mod_versions_id_fk" FOREIGN KEY ("version_id") REFERENCES "public"."mod_versions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mod_versions" ADD CONSTRAINT "mod_versions_mod_id_mods_id_fk" FOREIGN KEY ("mod_id") REFERENCES "public"."mods"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "mods" ADD CONSTRAINT "mods_owner_id_user_id_fk" FOREIGN KEY ("owner_id") REFERENCES "public"."user"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "crash_reports" ADD CONSTRAINT "crash_reports_user_id_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."user"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "telemetry_runs" ADD CONSTRAINT "telemetry_runs_user_id_user_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."user"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "mod_versions_mod_version_idx" ON "mod_versions" USING btree ("mod_id","version");--> statement-breakpoint
CREATE UNIQUE INDEX "mods_slug_idx" ON "mods" USING btree ("slug");--> statement-breakpoint
CREATE INDEX "mods_owner_idx" ON "mods" USING btree ("owner_id");--> statement-breakpoint
CREATE INDEX "mods_category_idx" ON "mods" USING btree ("category");--> statement-breakpoint
CREATE INDEX "crash_reports_created_idx" ON "crash_reports" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "crash_reports_class_idx" ON "crash_reports" USING btree ("error_class");--> statement-breakpoint
CREATE INDEX "telemetry_runs_created_idx" ON "telemetry_runs" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "telemetry_runs_ok_idx" ON "telemetry_runs" USING btree ("ok");