/**
 * Turn a thrown `RsmmError` message into something a player can act on.
 * The raw text ("rsmm json apply failed (exit 1): …") stays available in the
 * detail block below — this is the headline, not a replacement.
 */
export function explainError(message: string): { title: string; hint: string | null } {
  const text = message.toLowerCase();
  if (text.includes('rsmm cli not found')) {
    return {
      title: 'The rsmm command-line tool could not be found.',
      hint: 'Reinstall the app, or — if you run from source — install the CLI with `pip install -e .`.',
    };
  }
  if (text.includes('timed out')) {
    return {
      title: 'The command took too long and was stopped.',
      hint: 'Big mod sets can outrun the timeout. Try again, or run the command from a terminal to watch it work.',
    };
  }
  if (text.includes('returned invalid json')) {
    return {
      title: 'rsmm replied with something this app could not read.',
      hint: 'Usually a version mismatch between the app and the CLI. The raw reply is below.',
    };
  }
  if (text.includes('game') && (text.includes('not found') || text.includes('could not find'))) {
    return {
      title: 'Your Ravenswatch install could not be found.',
      hint: 'Set the game folder in Settings → Paths, then run the command again.',
    };
  }
  if (text.includes('permission denied') || text.includes('access is denied')) {
    return {
      title: 'rsmm was not allowed to touch those files.',
      hint: 'Close the game and Steam, then try again. On Windows the game folder may need elevated rights.',
    };
  }
  return { title: 'The command did not finish.', hint: null };
}
