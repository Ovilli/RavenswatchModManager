import { describe, expect, it } from 'vitest';
import robots from './robots';

const rules = () => {
  const r = robots().rules;
  return Array.isArray(r) ? r : [r];
};
const forAgent = (name: string) =>
  rules().find((rule) => rule.userAgent === name);

describe('robots', () => {
  it('keeps shared logs out of every training and search corpus', () => {
    for (const agent of ['GPTBot', 'ClaudeBot', 'Claude-SearchBot', 'CCBot', 'Google-Extended']) {
      const rule = forAgent(agent);
      expect(rule, `${agent} has no named rule`).toBeDefined();
      expect(rule?.disallow, agent).toContain('/l/');
    }
  });

  it('lets an on-demand agent read a shared log the user pointed it at', () => {
    // A share link exists to be handed to whoever is helping you, and that is
    // increasingly an assistant. Blocking these bought no privacy — the helper
    // was given the URL — and cost a support thread two rounds of a user
    // hand-pasting 78 KB of log into a chat window.
    for (const agent of ['Claude-User', 'ChatGPT-User', 'Perplexity-User']) {
      const rule = forAgent(agent);
      expect(rule, `${agent} has no named rule`).toBeDefined();
      expect(rule?.disallow, agent).not.toContain('/l/');
    }
  });

  it('still hides the account screens from every named agent', () => {
    for (const rule of rules()) {
      if (rule.userAgent === '*') continue;
      for (const path of ['/auth/', '/account', '/my-mods', '/publish', '/admin']) {
        expect(rule.disallow, `${rule.userAgent} ${path}`).toContain(path);
      }
    }
  });
});
