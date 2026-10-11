import pkg from '../../package.json';

/**
 * The launcher version stamped on shared logs and telemetry.
 *
 * Compiled in from package.json, which the release bump keeps equal to
 * tauri.conf.json. It used to read `VITE_RSMM_VERSION`, which no build ever
 * set, so every shared log and crash report said `0.0.0-dev`.
 */
export const RSMM_VERSION: string = pkg.version ?? '0.0.0';
