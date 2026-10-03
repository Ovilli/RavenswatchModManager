/**
 * Work the app should do once per launch, or once a minute, not once per screen.
 *
 * Every CLI call is a cold process start: the frozen sidecar unpacks itself each
 * time (about 0.4 s on a fast Linux disk, more on Windows where antivirus scans
 * each unpack), so a check that re-ran whenever a screen mounted cost a second or
 * two per navigation. Measured on a click-through of Library, Profiles, Settings,
 * Log and back, 17 sidecar processes started; the network update checks and
 * `doctor` alone were re-run every time the Library was reopened.
 *
 * Two shapes, both keyed:
 *  - {@link oncePerLaunch}: runs the first time, then hands back the same result
 *    until `fresh` asks again (the user pressed "Re-check", or changed a path).
 *  - {@link cachedFor}: remembers a result for a while, and forgets it the moment
 *    anything writes to the game or the mods folder ({@link noteGameStateChanged},
 *    called for every CLI command that is not known to be read-only), so a
 *    cached "all good" can never outlive an apply, a restore or a repair.
 */

let generation = 0;

/** Something that can change what a cached check would say just happened. */
export function noteGameStateChanged(): void {
  generation += 1;
}

const launch = new Map<string, Promise<unknown>>();

/** Run `run` the first time for `key`; later callers share that result. */
export function oncePerLaunch<T>(key: string, run: () => Promise<T>, fresh = false): Promise<T> {
  const have = launch.get(key);
  if (have && !fresh) return have as Promise<T>;
  const p = run();
  launch.set(key, p);
  // A failure is not worth keeping: the next caller should get to try again.
  p.catch(() => {
    if (launch.get(key) === p) launch.delete(key);
  });
  return p;
}

interface Entry {
  at: number;
  generation: number;
  value: Promise<unknown>;
}
const timed = new Map<string, Entry>();

/** Reuse the result for `key` while it is younger than `ttlMs` and nothing has written since. */
export function cachedFor<T>(
  key: string,
  ttlMs: number,
  run: () => Promise<T>,
  fresh = false,
): Promise<T> {
  const have = timed.get(key);
  if (!fresh && have && have.generation === generation && Date.now() - have.at < ttlMs) {
    return have.value as Promise<T>;
  }
  const value = run();
  timed.set(key, { at: Date.now(), generation, value });
  value.catch(() => {
    if (timed.get(key)?.value === value) timed.delete(key);
  });
  return value;
}

/** Store a result that was learned some other way (a real update reports the same fields a check does). */
export function prime<T>(key: string, value: T): void {
  timed.set(key, { at: Date.now(), generation, value: Promise.resolve(value) });
}

/** Tests only. */
export function resetSessionCache(): void {
  generation = 0;
  launch.clear();
  timed.clear();
}
