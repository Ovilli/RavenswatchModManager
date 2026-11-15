import { schema } from '@rsmm/db';
import {
  PRIVATE_ONLY_TAG,
  PRIVATE_ONLY_TAG_ALIASES,
  hasPrivateOnlyTag,
  setPrivateOnlyTag,
} from '@rsmm/schemas';
import { sql } from 'drizzle-orm';

const tagAliases = sql.join(
  PRIVATE_ONLY_TAG_ALIASES.map((tag) => sql`${tag}`),
  sql`, `,
);
// Match String.trim() in the shared classifier, including legacy Unicode whitespace.
const trimCharacters =
  ' \t\n\r\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff';
const restrictedTag = sql`lower(btrim(tag, ${trimCharacters})) in (${tagAliases})`;
const storedTags = sql`coalesce(${schema.mods.tags}, ARRAY[]::text[])`;

function tagArray(tags: string[]) {
  return sql`ARRAY[${sql.join(
    tags.map((tag) => sql`${tag}`),
    sql`, `,
  )}]::text[]`;
}

/** Evaluate the stored row at write time, including concurrent edits and first-upload races. */
export function preservePrivateOnlyTags(tags: string[]) {
  const next = tagArray(setPrivateOnlyTag(tags, hasPrivateOnlyTag(tags)));
  if (hasPrivateOnlyTag(tags)) return next;
  return sql`case when exists (
    select 1 from unnest(${storedTags}) as t(tag) where ${restrictedTag}
  ) then array_append(${next}, ${PRIVATE_ONLY_TAG}) else ${next} end`;
}

/** Admin changes only this label, preserving ordinary tags from the current row. */
export function setStoredPrivateOnlyTag(privateOnly: boolean) {
  const ordinaryTags = sql`ARRAY(
    select tag from unnest(${storedTags}) as t(tag) where not (${restrictedTag})
  )`;
  return privateOnly ? sql`array_append(${ordinaryTags}, ${PRIVATE_ONLY_TAG})` : ordinaryTags;
}
