# Agent instructions

## Pull requests that impact UX

Every PR that impacts user experience, including a draft PR, **MUST include before and after screenshots at the top of its description**, before the summary, rationale, or testing notes. This applies to visual changes, user-facing copy, interactions, and user flows.

- Capture the **Before** state from the PR's base branch and the **After** state from the proposed changes. Use comparable data, UI states, and viewport sizes so reviewers can see the effect of the change.
- Embed the actual screenshots in the PR description with clear **Before** and **After** labels. The images must render on GitHub; local file paths, placeholders, and text-only descriptions do not satisfy this requirement.
- For interaction or flow changes, show the affected states or steps. A recording may supplement the screenshots but does not replace them.
- Capture and upload the screenshots before opening the PR, including when opening it as a draft. If capture is blocked, report the blocker instead of opening a UX PR without the required images.

PRs with no UX impact do not require screenshots and should omit the screenshot section.
