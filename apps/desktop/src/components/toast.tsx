import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';

type ToastTone = 'default' | 'success' | 'error';

interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastApi {
  push: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);

  const push = useCallback((message: string, tone: ToastTone = 'default') => {
    const id = ++idRef.current;
    setToasts((cur) => [...cur, { id, message, tone }]);
    setTimeout(() => {
      setToasts((cur) => cur.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="true"
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`grimoire-card pointer-events-auto min-w-[240px] max-w-[420px] px-4 py-3 text-sm animate-fade-in ${
              t.tone === 'success'
                ? 'border-gilt/60 text-parchment'
                : t.tone === 'error'
                  ? 'border-crimson text-parchment'
                  : 'text-parchment'
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

interface PromptOptions {
  title: string;
  label?: string;
  initialValue?: string;
  placeholder?: string;
  submitLabel?: string;
  multiline?: boolean;
}

interface ConfirmOptions {
  title: string;
  body?: string;
  confirmLabel?: string;
  destructive?: boolean;
}

interface DialogApi {
  prompt: (opts: PromptOptions) => Promise<string | null>;
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
}

const DialogContext = createContext<DialogApi | null>(null);

export function useDialog(): DialogApi {
  const ctx = useContext(DialogContext);
  if (!ctx) throw new Error('useDialog must be used inside <DialogProvider>');
  return ctx;
}

type DialogState =
  | { kind: 'prompt'; opts: PromptOptions; resolve: (v: string | null) => void }
  | { kind: 'confirm'; opts: ConfirmOptions; resolve: (v: boolean) => void }
  | null;

export function DialogProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DialogState>(null);

  const api: DialogApi = {
    prompt: (opts) => new Promise((resolve) => setState({ kind: 'prompt', opts, resolve })),
    confirm: (opts) => new Promise((resolve) => setState({ kind: 'confirm', opts, resolve })),
  };

  return (
    <DialogContext.Provider value={api}>
      {children}
      {state ? <DialogModal state={state} onClose={() => setState(null)} /> : null}
    </DialogContext.Provider>
  );
}

function DialogModal({
  state,
  onClose,
}: {
  state: Exclude<DialogState, null>;
  onClose: () => void;
}) {
  const isPrompt = state.kind === 'prompt';
  const [value, setValue] = useState(isPrompt ? (state.opts.initialValue ?? '') : '');
  const inputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const confirmBtnRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const fieldId = useId();

  useEffect(() => {
    triggerRef.current = document.activeElement as HTMLElement | null;
    if (isPrompt) {
      if (state.kind === 'prompt' && state.opts.multiline) {
        textareaRef.current?.focus();
        textareaRef.current?.select();
      } else {
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    } else {
      confirmBtnRef.current?.focus();
    }
    const trigger = triggerRef.current;
    return () => {
      trigger?.focus?.();
    };
  }, [isPrompt, state]);

  function commit() {
    if (state.kind === 'prompt') state.resolve(value);
    else state.resolve(true);
    onClose();
  }

  function cancel() {
    if (state.kind === 'prompt') state.resolve(null);
    else state.resolve(false);
    onClose();
  }

  const opts = state.opts;
  const multiline = state.kind === 'prompt' && state.opts.multiline;

  return (
    <dialog
      open
      aria-label={opts.title}
      className="fixed inset-0 z-[70] flex items-center justify-center p-4 animate-fade-in"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          cancel();
        } else if (e.key === 'Enter' && !multiline) {
          e.preventDefault();
          commit();
        }
      }}
    >
      <div className="absolute inset-0 bg-pitch/80" onClick={cancel} />
      <div className="grimoire-card relative w-[min(480px,92vw)] p-5">
        <h3 className="font-fraktur text-xl text-parchment">{opts.title}</h3>
        {state.kind === 'confirm' && state.opts.body ? (
          <p className="font-serif-italic text-ash mt-2">{state.opts.body}</p>
        ) : null}
        {state.kind === 'prompt' ? (
          <div className="mt-3">
            {state.opts.label ? (
              <label htmlFor={fieldId} className="font-mono mb-1 block text-ash">
                {state.opts.label}
              </label>
            ) : null}
            {state.opts.multiline ? (
              <textarea
                id={fieldId}
                ref={textareaRef}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder={state.opts.placeholder}
                rows={4}
                className="font-mono w-full resize-none border border-border bg-pitch/60 p-3 text-parchment focus:border-gilt/60 focus:outline-none"
              />
            ) : (
              <input
                id={fieldId}
                ref={inputRef}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder={state.opts.placeholder}
                className="font-mono w-full border border-border bg-pitch/60 px-3 py-2 text-parchment focus:border-gilt/60 focus:outline-none"
              />
            )}
          </div>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            className="border border-border px-3 py-1.5 text-ash hover:text-parchment"
          >
            Cancel
          </button>
          <button
            type="button"
            ref={confirmBtnRef}
            onClick={commit}
            className={`border px-3 py-1.5 text-parchment transition-colors duration-150 ${
              state.kind === 'confirm' && state.opts.destructive
                ? 'border-crimson bg-crimson/80 hover:bg-oxblood'
                : 'border-crimson bg-crimson/80 hover:bg-oxblood'
            }`}
          >
            {state.kind === 'prompt'
              ? (state.opts.submitLabel ?? 'OK')
              : (state.opts.confirmLabel ?? 'OK')}
          </button>
        </div>
      </div>
    </dialog>
  );
}
