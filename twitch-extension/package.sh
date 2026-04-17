#!/usr/bin/env bash
# Build a Twitch CDN-ready ZIP of the extension.
# Usage: bash twitch-extension/package.sh [version]
# Output: twitch-extension-<version>.zip

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

# Twitch requires EBS_URL to be baked in at build time.
# Set TWITCH_EBS_URL before running this script.
if [ -z "$TWITCH_EBS_URL" ]; then
    echo "ERROR: TWITCH_EBS_URL is not set."
    echo "Usage: TWITCH_EBS_URL=https://your-ebs.example.com bash package.sh"
    exit 1
fi

echo "Building extension v${VERSION} pointing at ${TWITCH_EBS_URL}..."

# Create a temp directory with substituted EBS URLs
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

for f in "${FILES[@]}"; do
    sed "s|%%EBS_URL%%|${TWITCH_EBS_URL}|g" "$f" > "$TMPDIR/$f"
done

cd "$TMPDIR"
zip -r "$SCRIPT_DIR/$OUT" "${FILES[@]}" > /dev/null

echo "Created: twitch-extension/$OUT"
echo ""
echo "Next steps:"
echo "  1. Upload $OUT to https://dev.twitch.tv/console/extensions"
echo "  2. Set version status to 'Local Test' for testing, or submit for review."
