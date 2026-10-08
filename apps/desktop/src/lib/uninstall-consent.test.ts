/**
 * A mod's `on_disable.py` runs only on the user's yes.
 *
 * The script ships inside the mod's archive and runs as the user, outside the
 * game, with no sandbox. Uninstall used to run it unasked, so an asset-only
 * mod (which never runs any code while enabled) got arbitrary code execution
 * the moment it was removed. The CLI now answers `needsHookConsent` and waits
 * for `--run-hook` or `--skip-hook`; these pin the desktop half of that.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const invoke = vi.fn();
const sidecar = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...a: unknown[]) => invoke(...a) }));
vi.mock('@tauri-apps/plugin-shell', () => ({
  Command: { sidecar: (...a: unknown[]) => sidecar(...a), create: vi.fn() },
}));

/** A sidecar handle that runs and closes cleanly with `stdout`. */
function workingSidecar(stdout: string) {
  const handlers: Record<string, (arg: unknown) => void> = {};
  return {
    stdout: { on: (_e: string, cb: (c: string) => void) => cb(stdout) },
    stderr: { on: vi.fn() },
    on: (event: string, cb: (arg: unknown) => void) => {
      handlers[event] = cb;
    },
    spawn: () => {
      setTimeout(() => handlers.close?.({ code: 0 }), 0);
      return Promise.resolve({ pid: 1234, kill: vi.fn() });
    },
  };
}

const NEEDS_CONSENT = JSON.stringify({
  ok: false,
  modId: 'seedy',
  needsHookConsent: true,
  hookPath: '/mods/seedy/on_disable.py',
  error: 'seedy ships on_disable.py',
});

/** The bridge argv of every sidecar call, `json` stripped. */
const calls = () => sidecar.mock.calls.map((c) => (c[1] as string[]).slice(1));

beforeEach(() => {
  invoke.mockReset();
  sidecar.mockReset();
  invoke.mockImplementation(async (cmd: string) => {
    if (cmd === 'rsmm_runtime_env') return { repoRoot: '/repo', path: '/usr/bin' };
    throw new Error(`unexpected invoke ${cmd}`);
  });
});

async function freshRsmm() {
  vi.resetModules();
  return import('./rsmm');
}

describe('uninstallLocalMod', () => {
  it('runs the hook only after the user says yes', async () => {
    sidecar
      .mockImplementationOnce(() => workingSidecar(NEEDS_CONSENT))
      .mockImplementationOnce(() => workingSidecar('{"ok":true,"disableHook":"ok"}'));
    const { uninstallLocalMod } = await freshRsmm();
    const ask = vi.fn(async () => true);

    const result = await uninstallLocalMod('seedy', ask);

    expect(ask).toHaveBeenCalledWith('seedy');
    expect(calls()).toEqual([
      ['uninstall-mod', 'seedy'],
      ['uninstall-mod', 'seedy', '--run-hook'],
    ]);
    expect(result?.ok).toBe(true);
  });

  it('removes the mod without running the hook on a no', async () => {
    sidecar
      .mockImplementationOnce(() => workingSidecar(NEEDS_CONSENT))
      .mockImplementationOnce(() => workingSidecar('{"ok":true,"disableHook":"skipped"}'));
    const { uninstallLocalMod } = await freshRsmm();

    const result = await uninstallLocalMod('seedy', async () => false);

    expect(calls()[1]).toEqual(['uninstall-mod', 'seedy', '--skip-hook']);
    expect(result?.disableHook).toBe('skipped');
  });

  it('never runs the hook when there is no way to ask', async () => {
    sidecar
      .mockImplementationOnce(() => workingSidecar(NEEDS_CONSENT))
      .mockImplementationOnce(() => workingSidecar('{"ok":true,"disableHook":"skipped"}'));
    const { uninstallLocalMod } = await freshRsmm();

    await uninstallLocalMod('seedy');

    expect(calls()[1]).toEqual(['uninstall-mod', 'seedy', '--skip-hook']);
  });

  it('does not ask when the mod has no hook to run', async () => {
    sidecar.mockImplementationOnce(() => workingSidecar('{"ok":true,"disableHook":"absent"}'));
    const { uninstallLocalMod } = await freshRsmm();
    const ask = vi.fn(async () => true);

    await uninstallLocalMod('plain', ask);

    expect(ask).not.toHaveBeenCalled();
    expect(calls()).toEqual([['uninstall-mod', 'plain']]);
  });

  it('reports a skipped hook as cleanup that did not run', async () => {
    const { disableHookWarning } = await freshRsmm();
    expect(disableHookWarning({ ok: true, modId: 'seedy', disableHook: 'skipped' })).toMatch(
      /did not run \(skipped\)/,
    );
  });
});
