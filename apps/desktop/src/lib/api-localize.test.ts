import { describe, expect, it } from 'vitest';
import { localizeMod } from './api';

const mod = {
  name: 'Stronger Enemies',
  summary: 'Tougher enemies.',
  description: 'Long English text.',
  translations: { 'ZH-S': { name: '更强的敌人', summary: '敌人更强。' } },
};

describe('localizeMod', () => {
  it('lays the locale over English, field by field', () => {
    expect(localizeMod(mod, 'ZH-S')).toMatchObject({
      name: '更强的敌人',
      summary: '敌人更强。',
      description: 'Long English text.',
    });
  });

  it('leaves the mod alone without a matching translation', () => {
    expect(localizeMod(mod, 'EN')).toBe(mod);
    expect(localizeMod({ ...mod, translations: null }, 'ZH-S').name).toBe('Stronger Enemies');
  });
});
