import { describe, expect, it } from 'vitest';
import { parseLauncherLog } from './launcher-log';

describe('parseLauncherLog', () => {
  it('splits a written line into time, level and message', () => {
    const [entry] = parseLauncherLog('1754500000 [INFO] Launch requested: modded');
    expect(entry).toEqual({
      at: 1754500000000,
      level: 'info',
      message: 'Launch requested: modded',
      context: null,
      raw: '1754500000 [INFO] Launch requested: modded',
    });
  });

  it('peels off the context tail without eating the message', () => {
    const [entry] = parseLauncherLog(
      '1754500001 [ERROR] modded launch failed (exit 1) | context={"code":1}',
    );
    expect(entry?.message).toBe('modded launch failed (exit 1)');
    expect(entry?.context).toBe('{"code":1}');
  });

  it('keeps unparseable lines readable instead of dropping them', () => {
    const [entry] = parseLauncherLog('a line from some older build');
    expect(entry?.level).toBe('other');
    expect(entry?.at).toBeNull();
    expect(entry?.message).toBe('a line from some older build');
  });

  it('skips blank lines and trailing newlines', () => {
    expect(parseLauncherLog('\n\n  \n')).toEqual([]);
    expect(parseLauncherLog('1754500000 [WARN] hm\n')).toHaveLength(1);
  });

  it('classifies an unknown level as other rather than guessing', () => {
    const [entry] = parseLauncherLog('1754500000 [TRACE] verbose thing');
    expect(entry?.level).toBe('other');
    expect(entry?.message).toBe('verbose thing');
  });

  it('does not let a message quoting a level forge that level', () => {
    // The writer escapes CR/LF, so a forged record lands inside `message`.
    const entries = parseLauncherLog('1754500000 [INFO] CLI said: [ERROR] disk full');
    expect(entries).toHaveLength(1);
    expect(entries[0]?.level).toBe('info');
    expect(entries.filter((e) => e.level === 'error')).toEqual([]);
  });
});
