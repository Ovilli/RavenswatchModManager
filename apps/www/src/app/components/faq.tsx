import { faqs } from './faq-data';

/**
 * Native <details>: keyboard and screen-reader support for free, works without
 * JavaScript, and the answers stay in the HTML that crawlers read.
 */
export function FAQ() {
  return (
    <div className="mt-10 grid gap-x-12 md:grid-cols-2">
      {faqs.map((faq) => (
        <details key={faq.q} className="faq-item group border-b border-border/70">
          <summary className="flex cursor-pointer list-none items-baseline justify-between gap-6 py-5 text-xl text-parchment hover:text-gilt">
            <span>{faq.q}</span>
            <span
              className="shrink-0 text-2xl leading-none text-gilt transition-transform duration-200 group-open:rotate-45"
              aria-hidden="true"
            >
              +
            </span>
          </summary>
          <p className="pb-6 text-lg leading-relaxed text-parchment/70">{faq.a}</p>
        </details>
      ))}
    </div>
  );
}
