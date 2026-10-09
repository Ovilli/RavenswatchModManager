import type { ModListItem, ModTranslation } from '@rsmm/schemas';
import type { Locale } from './i18n';

/**
 * Store-listing translation: which language to ask the API for, and which text
 * to show. The API serves a machine translation BESIDE the original; the UI
 * shows it only while the user has not asked for the original, and always
 * marks it as machine-translated.
 */

/** The `lang` to send the API, or undefined when listings are shown as written. */
export function listingLang(locale: Locale, enabled: boolean): string | undefined {
  return enabled && locale !== 'en' ? locale : undefined;
}

/** The translation to display, when there is a usable one. */
export function usableTranslation(
  mod: Pick<ModListItem, 'translation'> | undefined | null,
  lang: string | undefined,
): ModTranslation | null {
  const t = mod?.translation;
  return lang && t && t.lang === lang ? t : null;
}

/**
 * The item as the list shows it: the translated name and summary laid over the
 * original, which stays reachable as `originalName` for a tooltip.
 */
export function displayListing<T extends Pick<ModListItem, 'name' | 'summary' | 'translation'>>(
  mod: T,
  lang: string | undefined,
): T & { originalName?: string } {
  const t = usableTranslation(mod, lang);
  if (!t) return mod;
  return {
    ...mod,
    name: t.name ?? mod.name,
    summary: t.summary ?? mod.summary,
    originalName: mod.name,
  };
}
