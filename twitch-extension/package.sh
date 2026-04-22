#!/usr/bin/env bash
# Build a Twitch CDN-ready ZIP of the extension.
# Usage: bash twitch-extension/package.sh [version]
# Output: twitch-extension-<version>.zip
#
# The EBS URL is no longer baked in at build time — it is read at runtime
# from Twitch.ext.configuration.global (set once in the Twitch Extensions console).

set -e

VERSION=${1:-"1.0.0"}
OUT="twitch-extension-${VERSION}.zip"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Files to include (dev-harness and package.sh are excluded)
FILES=(
    panel.html
    config.html
    live_config.html
    extension.js
    extension.css
)

cd "$SCRIPT_DIR"

echo "Packaging extension v${VERSION}..."
zip -r "$SCRIPT_DIR/$OUT" "${FILES[@]}" > /dev/null

echo "Created: twitch-extension/$OUT"
echo ""
echo "Next steps:"
echo "  1. Upload $OUT to https://dev.twitch.tv/console/extensions"
echo "  2. Set version status to 'Local Test' for testing, or submit for review."
echo "  3. Set the EBS URL once via the Twitch Extensions Configuration Service:"
echo "     PUT https://api.twitch.tv/helix/extensions/configurations"
echo '     body: {"extension_id":"<id>","segment":"global","content":"{\"ebs_url\":\"https://your-ebs.example.com\"}"}'
