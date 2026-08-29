import { msg } from './i18n';

/**
 * Turn a thrown `RsmmError` message into something a player can act on.
 * The raw text ("rsmm json apply failed (exit 1): …") stays available in the
 * detail block below — this is the headline, not a replacement.
 *
 * Returns ENGLISH sources wrapped in `msg()`: this table is called from plain
 * functions as well as components, so the translation happens at the render
 * site (`t(title)`), not here.
 */
export function explainError(message: string): { title: string; hint: string | null } {
  const text = message.toLowerCase();
  if (text.includes('rsmm cli not found')) {
    return {
      title: msg('The rsmm command-line tool could not be found.'),
      hint: msg(
        'Reinstall the app, or — if you run from source — install the CLI with `pip install -e .`.',
      ),
    };
  }
  if (text.includes('timed out')) {
    return {
      title: msg('The command took too long and was stopped.'),
      hint: msg(
        'Big mod sets can outrun the timeout. Try again, or run the command from a terminal to watch it work.',
      ),
    };
  }
  if (text.includes('returned invalid json')) {
    return {
      title: msg('rsmm replied with something this app could not read.'),
      hint: msg('Usually a version mismatch between the app and the CLI. The raw reply is below.'),
    };
  }
  if (text.includes('game') && (text.includes('not found') || text.includes('could not find'))) {
    return {
      title: msg('Your Ravenswatch install could not be found.'),
      hint: msg('Set the game folder in Settings → Paths, then run the command again.'),
    };
  }
  if (text.includes('permission denied') || text.includes('access is denied')) {
    return {
      title: msg('rsmm was not allowed to touch those files.'),
      hint: msg(
        'Close the game and Steam, then try again. On Windows the game folder may need elevated rights.',
      ),
    };
  }
  return { title: msg('The command did not finish.'), hint: null };
}
