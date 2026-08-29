/**
 * React binding for `lib/i18n`.
 *
 * Kept apart from the core so the core stays importable from plain modules
 * (and from the coverage test) without pulling in React or the store.
 */

import { Fragment, type ReactNode, useMemo } from 'react';
import { useApp } from '../store';
import { type Locale, type Vars, localeTag, translate } from './i18n';

export type TFunction = ((message: string, vars?: Vars) => string) & {
  /** English pluralisation resolved at the call site. See `i18n.plural`. */
  n: (count: number, one: string, other: string, vars?: Vars) => string;
  locale: Locale;
  /** `Intl` tag, for `toLocaleDateString` and friends. */
  tag: string;
};

export function useLocale(): Locale {
  return useApp((s) => s.settings.language);
}

/**
 * The translator for the active language.
 *
 * Subscribes to the language setting, so every component holding a `t` from
 * this hook re-renders on a language change — that is what makes switching
 * languages instant instead of a restart.
 */
export function useT(): TFunction {
  const locale = useLocale();
  return useMemo(() => {
    const fn = ((message: string, vars?: Vars) => translate(locale, message, vars)) as TFunction;
    fn.n = (count, one, other, vars) =>
      translate(locale, count === 1 ? one : other, { n: count, ...vars });
    fn.locale = locale;
    fn.tag = localeTag(locale);
    return fn;
  }, [locale]);
}

/**
 * A translated message whose placeholders are React nodes.
 *
 * For a sentence that carries markup mid-way — a version in a `<span>`, a
 * `<Link>`, a `<code>` — where splitting it into "before" and "after" strings
 * would hand the translator two fragments they cannot reorder. Pass the whole
 * sentence through `t()` and name each node:
 *
 * ```tsx
 * <TParts
 *   text={t('RSMM updated to {version}.')}
 *   parts={{ version: <span className="font-mono">v{current}</span> }}
 * />
 * ```
 *
 * An unmatched placeholder renders as its literal `{name}`, the same rule the
 * string interpolator uses — a translator's typo must be visible, not silent.
 */
export function TParts({
  text,
  parts,
}: {
  text: string;
  parts: Record<string, ReactNode>;
}): ReactNode {
  const pieces = text.split(/(\{\w+\})/g);
  return (
    <>
      {pieces.map((piece, i) => {
        const name = /^\{(\w+)\}$/.exec(piece)?.[1];
        const node = name ? parts[name] : undefined;
        // Positional keys: the pieces are a fixed split of one string, and
        // nothing is inserted or reordered between renders.
        // biome-ignore lint/suspicious/noArrayIndexKey: see above
        return <Fragment key={i}>{node ?? piece}</Fragment>;
      })}
    </>
  );
}
