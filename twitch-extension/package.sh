#!/usr/bin/env bash
# Build a Twitch CDN-ready ZIP of the extension.
# Usage: bash twitch-extension/package.sh <version>
# Output: twitch-extension/twitch-extension-<version>.zip
#
# The EBS URL is no longer baked in at build time — it is read at runtime
# from Twitch.ext.configuration.global (set once in the Twitch Extensions console).

set -e

VERSION=${1:?"Usage: package.sh <version>  (e.g. 1.1.6)"}
OUT="twitch-extension-${VERSION}.zip"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Files to include (dev-harness and package.sh are excluded)
FILES=(
    panel.html
    panel.js
    config.html
    config.js
    live_config.html
    live_config.js
    extension.js
    extension.css
)

cd "$SCRIPT_DIR"

if [ -e "$SCRIPT_DIR/$OUT" ]; then
    echo "ERROR: $OUT already exists — bump the version." >&2
    exit 1
fi

# Every local src/href in a packaged HTML file must be in FILES.
for html in "${FILES[@]}"; do
    [[ "$html" == *.html ]] || continue
    for ref in $(grep -oE '(src|href)="[^"]+"' "$html" | cut -d'"' -f2 | grep -vE '^((https?:)?//|#|data:|mailto:)'); do
        if ! printf '%s\n' "${FILES[@]}" | grep -qxF "$ref"; then
            echo "ERROR: $html references $ref, which is not packaged." >&2
            exit 1
        fi
    done
done

echo "Packaging extension v${VERSION}..."
zip "$SCRIPT_DIR/$OUT" "${FILES[@]}" > /dev/null

echo "Created: twitch-extension/$OUT"
echo ""
echo "Dev console → Version → Asset Hosting:"
echo "  Panel Viewer Path:  panel.html"
echo "  Config Path:        config.html"
echo "  Live Config Path:   live_config.html"
echo "Dev console → Version → Capabilities → Allowlist for URL Fetching Domains:"
echo "  https://kana-cards.com"
echo "Upload the zip, move the version to Hosted Test, verify all three views, then submit."
