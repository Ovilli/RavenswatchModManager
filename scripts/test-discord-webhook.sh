#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export "$(grep -E '^DISCORD_WEBHOOK_URL=' "$REPO_DIR/.env" | head -1)"

if [ -z "${DISCORD_WEBHOOK_URL:-}" ]; then
  echo "Error: DISCORD_WEBHOOK_URL not found in .env"
  exit 1
fi

echo "Fetching latest release from GitHub..."
RESULT=$(curl -sf "https://api.github.com/repos/Ovilli/RavenswatchModManager/releases/latest" 2>/dev/null || echo '{"message":"Not Found"}')

PAYLOAD=$(node -e "
const latest = JSON.parse(process.argv[1]);

let body, tag, name, url, isPre;

if (latest.message === 'Not Found') {
  body  = '## Added\n\u2022 New mod registry browser\n\u2022 Lua scripting support\n\u2022 Profile management\n\n## Fixed\n\u2022 Crash on large mod packs\n\u2022 UI flicker on Linux';
  tag   = 'v0.1.0';
  name  = 'RSMM v0.1.0';
  url   = 'https://github.com/Ovilli/RavenswatchModManager/releases/tag/' + tag;
  isPre = false;
} else {
  body  = latest.body || 'No release notes.';
  tag   = latest.tag_name;
  name  = latest.name || tag;
  url   = latest.html_url;
  isPre = latest.prerelease;
}

const emoji = isPre ? '\uD83E\uDD2A' : '\uD83D\uDE80';
const label = isPre ? ' (pre-release)' : '';
const desc = body.slice(0, 2000);
const banner = 'https://raw.githubusercontent.com/Ovilli/RavenswatchModManager/main/apps/desktop/src-tauri/icons/update-banner.png';

console.log(JSON.stringify({
  username: 'RSMM',
  avatar_url: 'https://github.com/Ovilli/RavenswatchModManager/raw/main/apps/desktop/src-tauri/icons/raven-avatar.png',
  content: emoji + ' **' + name + '**' + label,
  embeds: [{
    title: 'Ravenswatch Mod Manager',
    url: url,
    color: 8921129,
    description: desc,
    image: { url: banner },
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
" "$RESULT")

echo "Sending to Discord..."
curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD"

echo ""
echo "Done! Check your Discord channel."
