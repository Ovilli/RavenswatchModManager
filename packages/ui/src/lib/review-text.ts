export type ReviewTranslator = (message: string, vars?: Record<string, string | number>) => string;

export const reviewText: ReviewTranslator = (message, vars) =>
  message.replace(/\{(\w+)\}/g, (match, name: string) => String(vars?.[name] ?? match));

export interface ReviewTextOptions {
  t?: ReviewTranslator;
  locale?: string;
}
