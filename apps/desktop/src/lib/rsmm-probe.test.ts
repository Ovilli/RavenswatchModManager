/**
 * The program-discovery state machine in `rsmm.ts`.
 *
 * Its own file rather than a block in `rsmm.test.ts` because these cases need
 * a FRESH module per test: `resolvedProg` and `useRustProbe` are module-level
 * and the whole point here is what the second call does with what the first
 * one learned.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const invoke = vi.fn();
const sidecar = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...a: unknown[]) => invoke(...a) }));
vi.mock('@tauri-apps/plugin-shell', () => ({
  Command: { sidecar: (...a: unknown[]) => sidecar(...a), create: vi.fn() },
}));

/** A sidecar handle whose spawn fails the way a missing binary does. */
function missingSidecar() {
  return {
    stdout: { on: vi.fn() },
    stderr: { on: vi.fn() },
    on: vi.fn(),
    spawn: () => Promise.reject(new Error('program not found')),
  };
}

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
      // Close on the next tick: the listeners are registered synchronously
      // before `spawn()` resolves, exactly as the real plugin does it.
      setTimeout(() => handlers.close?.({ code: 0 }), 0);
      return Promise.resolve({ pid: 1234, kill: vi.fn() });
    },
  };
}

async function freshRsmm() {
  vi.resetModules();
  return import('./rsmm');
}

beforeEach(() => {
  invoke.mockReset();
  sidecar.mockReset();
  // `rsmm_runtime_env` is asked for once per command to build PATH.
  invoke.mockImplementation(async (cmd: string) => {
    if (cmd === 'rsmm_runtime_env') return { repoRoot: '/repo', path: '/usr/bin' };
    if (cmd === 'probe_rsmm') return { code: 0, stdout: '[]', stderr: '' };
    throw new Error(`unexpected invoke ${cmd}`);
  });
});

describe('program discovery', () => {
  it('stops re-attempting the sidecar once the Rust probe is adopted', async () => {
    // The regression: adopting the Rust probe never set `resolvedProg`, so
    // every later call re-entered discovery, re-failed the sidecar spawn and
    // only then reached the probe — a wasted spawn per command, forever, with
    // the adopted-probe fast path sitting unreachable behind it.
    sidecar.mockImplementation(() => missingSidecar());
    const { listLocalMods } = await freshRsmm();

    await listLocalMods();
    expect(sidecar).toHaveBeenCalledTimes(1);

    await listLocalMods();
    await listLocalMods();
    expect(sidecar).toHaveBeenCalledTimes(1);
    expect(invoke.mock.calls.filter(([c]) => c === 'probe_rsmm')).toHaveLength(3);
  });

  it('hands the per-profile environment to the Rust probe', async () => {
    // Without this the probe path ran against the CLI's DEFAULT mods dir no
    // matter which profile was active, silently undoing profile isolation.
    sidecar.mockImplementation(() => missingSidecar());
    const { listLocalModsForProfile } = await freshRsmm();

    await listLocalModsForProfile('keeper');

    const call = invoke.mock.calls.find(([c]) => c === 'probe_rsmm');
    expect(call).toBeDefined();
    const payload = call?.[1] as { args: string[]; env: Record<string, string> };
    expect(payload.args).toEqual(['json', 'list']);
    expect(payload.env.RSMM_MODS_DIR).toMatch(/profiles\/keeper$/);
  });

  it('never falls through to the probe when the sidecar works', async () => {
    sidecar.mockImplementation(() => workingSidecar('[]'));
    const { listLocalMods } = await freshRsmm();

    await listLocalMods();
    await listLocalMods();

    expect(sidecar).toHaveBeenCalledTimes(2);
    expect(invoke.mock.calls.filter(([c]) => c === 'probe_rsmm')).toHaveLength(0);
  });

  it('tracks the child of a non-streaming command so quit can kill it', async () => {
    // `execute()` returned a finished result and no handle, so these children
    // were invisible to `killLiveChildren` — which is the orphaned `rsmm.exe`
    // holding the mods folder that lib/quit.ts exists to prevent.
    const kill = vi.fn(async () => {});
    const handlers: Record<string, (arg: unknown) => void> = {};
    sidecar.mockImplementation(() => ({
      stdout: { on: (_e: string, cb: (c: string) => void) => cb('[]') },
      stderr: { on: vi.fn() },
      on: (event: string, cb: (arg: unknown) => void) => {
        handlers[event] = cb;
      },
      spawn: () => Promise.resolve({ pid: 99, kill }),
    }));
    const { listLocalMods, liveChildCount, killLiveChildren } = await freshRsmm();

    const pending = listLocalMods();
    await vi.waitFor(() => expect(liveChildCount()).toBe(1));

    await killLiveChildren();
    expect(kill).toHaveBeenCalledTimes(1);

    handlers.close?.({ code: 0 });
    await pending;
    expect(liveChildCount()).toBe(0);
  });
});
