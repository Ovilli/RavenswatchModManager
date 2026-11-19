# Library list and toolbar preview

Before screenshots: `main` at `18ba26efbb00b8863c0757deeca7b28bb4fcaf76`.
After screenshots: UI implementation at `fd7a54eef1a7767993bdc6de046b8fad4c8c7bb8`.

Captured at 1099 × 952 with the same 16 fictional mods, My mods profile, expanded sidebar, English locale, dark appearance, and Load order sort.

The base branch was exported to a temporary directory and given only the browser fixture adapter, isolated preview storage, and preview initialization/banner. Its Library route and shared UI components/styles remain byte-for-byte identical to the base branch. This supplies comparable populated data without the native CLI. The base and proposed app used separate browser sessions.

- `library-before.jpg` / `library-after.jpg`: initial Library view (cards on the base, list after).
- `filters-before.jpg` / `filters-after.jpg`: Disabled status and Gameplay category applied, showing the same Boss Rush mod.
- `filter-dialog-after.jpg`: selecting those filters before pressing Show mods.

Run `pnpm --filter desktop dev:library` to explore the proposed preview. Changes stay in memory and reset on reload. These screenshots cover browser UI; native installs and game execution were not exercised.
