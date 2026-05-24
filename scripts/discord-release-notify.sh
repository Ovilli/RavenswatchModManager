#!/usr/bin/env bash
# Post a release announcement to Discord.
#
# Env:
#   DISCORD_WEBHOOK or DISCORD_WEBHOOK_URL — webhook URL (required to send)
#   TAG — release tag, e.g. v0.3.5 (required)
#   REPO — owner/name (default: Ovilli/RavenswatchModManager)
#   RELEASE_URL, RELEASE_NAME, RELEASE_BODY, PRERELEASE — optional; fetched
#     via `gh release view` when GH_TOKEN/gh is available and fields are unset
#
# Used from:
#   - .github/workflows/release.yml (finalize-release) — GITHUB_TOKEN publish
#     does not fire `release: published`, so we notify here.
#   - .github/workflows/discord-notify.yml — manual/UI publishes still use that hook.

set -euo pipefail

WEBHOOK="${DISCORD_WEBHOOK:-${DISCORD_WEBHOOK_URL:-}}"
if [ -z "$WEBHOOK" ]; then
  echo "DISCORD_WEBHOOK_URL not set — skipping"
  exit 0
fi

TAG="${TAG:?TAG is required}"
REPO="${REPO:-Ovilli/RavenswatchModManager}"

if [ -z "${RELEASE_URL:-}" ] && command -v gh >/dev/null 2>&1; then
  if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
    RELEASE_URL="${RELEASE_URL:-$(gh release view "$TAG" --repo "$REPO" --json url -q .url)}"
    RELEASE_NAME="${RELEASE_NAME:-$(gh release view "$TAG" --repo "$REPO" --json name -q .name)}"
    RELEASE_BODY="${RELEASE_BODY:-$(gh release view "$TAG" --repo "$REPO" --json body -q .body)}"
    PRERELEASE="${PRERELEASE:-$(gh release view "$TAG" --repo "$REPO" --json isPrerelease -q .isPrerelease)}"
  fi
fi

export RELEASE_TAG="$TAG"
export RELEASE_URL="${RELEASE_URL:-https://github.com/${REPO}/releases/tag/${TAG}}"
export RELEASE_NAME="${RELEASE_NAME:-$TAG}"
export RELEASE_BODY="${RELEASE_BODY:-}"
export PRERELEASE="${PRERELEASE:-false}"
export REPO

BANNER="https://raw.githubusercontent.com/${REPO}/main/apps/desktop/src-tauri/icons/update-banner.png?v=${TAG}"

PAYLOAD=$(node -e "
  const tag = process.env.RELEASE_TAG || '';
  const body = (process.env.RELEASE_BODY || '').slice(0, 2000);
  const isPre = process.env.PRERELEASE === 'true';
  const emoji = isPre ? '\uD83E\uDD2A' : '\uD83D\uDE80';
  const name = process.env.RELEASE_NAME || tag;
  const url = process.env.RELEASE_URL;
  const repo = process.env.REPO;

  console.log(JSON.stringify({
    username: 'RSMM',
    avatar_url: 'https://github.com/' + repo + '/raw/main/apps/desktop/src-tauri/icons/raven-avatar.png',
    content: emoji + ' **' + name + '**' + (isPre ? ' (pre-release)' : ''),
    embeds: [{
      title: 'Ravenswatch Mod Manager',
      url: url,
      color: 8921129,
      description: body || 'No release notes.',
      image: { url: '$BANNER' },
      fields: [
        {
          name: '\uD83D\uDCC2 Full Changelog',
          value: '[View on GitHub](' + url + ')',
          inline: true
        },
        {
          name: '\uD83D\uDCE6 Downloads',
          value: '[Windows](' + url + ') \u00B7 [macOS](' + url + ') \u00B7 [Linux](' + url + ')',
          inline: true
        }
      ],
      footer: { text: tag + ' \u00B7 Ravenswatch Mod Manager' },
      timestamp: new Date().toISOString()
    }]
  }));
")

curl -sf -X POST "$WEBHOOK" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD"

echo "Discord notification sent for ${TAG}"
