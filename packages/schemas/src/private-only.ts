export const PRIVATE_ONLY_TAG = 'private-only';
// Keep previously published cheat tags protected and display them with the new label.
export const PRIVATE_ONLY_TAG_ALIASES = [
  'private-only',
  'private only',
  'private-games-only',
  'private games only',
  'cheat',
  'cheats',
];

export function isPrivateOnlyTag(tag: string): boolean {
  return PRIVATE_ONLY_TAG_ALIASES.includes(tag.trim().toLowerCase());
}

export function hasPrivateOnlyTag(tags: readonly string[] | null | undefined): boolean {
  return tags?.some(isPrivateOnlyTag) ?? false;
}

export function setPrivateOnlyTag(tags: readonly string[], privateOnly: boolean): string[] {
  const ordinaryTags = tags.filter((tag) => !isPrivateOnlyTag(tag));
  return privateOnly ? [...ordinaryTags, PRIVATE_ONLY_TAG] : ordinaryTags;
}
