<!-- Every PR that impacts UX, including a draft, MUST begin with before/after
screenshots, before "What and why". Follow AGENTS.md. Embed actual images that
render on GitHub and replace the placeholders before opening the PR.
For PRs with no UX impact, remove this section. -->

## Before / after

| Before | After |
| --- | --- |
| <!-- Embed screenshot from the base branch. --> | <!-- Embed screenshot from the proposed changes. --> |

## What and why

<!-- What this changes and the problem it solves. Link the issue if there is one. -->

## How I tested it

<!-- Commands you ran, and for in-game changes what you saw in game. -->

- [ ] `ruff check .` and `pnpm test:python:fast` pass
- [ ] `rsmm symbols gen` run if `data/symbols.json` changed
- [ ] No game files, no hardcoded engine addresses, nothing that unlocks paid content
