import { Cpu } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { ackDisclosure, disclosureAck } from '../lib/first-run';
import { Button } from './chrome';

/**
 * Revision of the disclosure text below. Bump it when the substance changes —
 * not for a typo — and every user is shown the new text once. The stored ack
 * records the revision, so a bump re-prompts without clearing anyone's other
 * first-run state.
 */
export const DISCLOSURE_REVISION = '1';

/** External links used in the disclosure. Opened through the OS browser. */
const REPO_URL = 'https://github.com/Ovilli/RavenswatchModManager';

async function openExternal(url: string): Promise<void> {
  try {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    await openUrl(url);
  } catch {
    window.open(url, '_blank', 'noreferrer,noopener');
  }
}

/**
 * One-time notice describing where AI assistance sits in this project's
 * toolchain.
 *
 * Written to be read as a tooling note rather than a warning label: the claim
 * it makes is specific and checkable (what AI was used for, what the machine
 * checks are, where the evidence lives), because a vague "some AI was involved"
 * tells a user nothing they can act on and invites the assumption that nothing
 * was verified.
 *
 * Gates the changelog dialog — see `FirstRunDialogs` — so a returning user is
 * never shown two stacked modals.
 */
export function AiDisclosureDialog({ onAcknowledged }: { onAcknowledged?: () => void }) {
  const [open, setOpen] = useState(false);

  // biome-ignore lint/correctness/useExhaustiveDependencies: mount-only — the ack is read from storage, and re-running on a new onAcknowledged identity would reopen a dialog the user just closed
  useEffect(() => {
    if (disclosureAck() !== DISCLOSURE_REVISION) setOpen(true);
    else onAcknowledged?.();
  }, []);

  if (!open) return null;

  const accept = () => {
    ackDisclosure(DISCLOSURE_REVISION);
    setOpen(false);
    onAcknowledged?.();
  };

  return createPortal(
    <div
      // biome-ignore lint/a11y/useSemanticElements: <dialog> needs an imperative showModal() and brings its own top-layer backdrop, which fights the app's overlay z-order; the other modals here use the same role="dialog" pattern
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-disclosure-title"
      className="fixed inset-0 z-[85] flex items-center justify-center p-4 animate-fade-in"
    >
      <div className="absolute inset-0 bg-pitch/90" />
      <div className="grimoire-card relative flex max-h-[88vh] w-[min(620px,94vw)] flex-col p-6">
        <header className="flex items-start gap-3">
          <div>
            <h2 id="ai-disclosure-title" className="font-fraktur text-2xl text-parchment">
              How this project was built
            </h2>
            <p className="font-serif-italic mt-1 text-ash">
              A one-time note on the tools behind RSMM. It will not appear again.
            </p>
          </div>
        </header>

        <div className="mt-4 min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
          <p className="font-serif-italic leading-relaxed text-parchment/90">
            Ravenswatch ships no modding API. Everything RSMM does had to be reverse-engineered from
            the shipped executable and its data files: the cooked-asset cipher, the engine function
            map, the Lua scripting layer. That work was done with the usual instruments. Ghidra, a
            disassembler, pattern scanners, custom miners, and a great deal of in-game testing. An
            AI coding assistant (Claude) was one of those instruments, used for reading decompiler
            output, drafting analysis tooling, and writing application code.
          </p>
        </div>
        <footer className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
          <Button type="button" size="sm" onClick={() => void openExternal(REPO_URL)}>
            View the source
          </Button>
          <Button type="button" size="sm" variant="primary" onClick={accept}>
            Understood
          </Button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
