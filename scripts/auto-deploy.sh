#!/bin/bash
# Auto-deploy: polls GitHub releases and restarts the container when a new version is published.
#
# Setup on the host:
#   chmod +x scripts/auto-deploy.sh
#   crontab -e
#   # add: */15 * * * * /path/to/repo/scripts/auto-deploy.sh >> /path/to/repo/deploy.log 2>&1

set -euo pipefail

REPO="${GITHUB_REPOSITORY:-ville-solja/FantasyLeague}"
COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$COMPOSE_DIR/.deployed-version"

CURRENT=$(cat "$VERSION_FILE" 2>/dev/null || echo "none")

LATEST=$(curl -sf "https://api.github.com/repos/$REPO/releases/latest" \
  | grep '"tag_name"' | head -1 | cut -d'"' -f4)

if [ -z "$LATEST" ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] No releases found — skipping"
  exit 0
fi

if [ "$LATEST" = "$CURRENT" ]; then
  exit 0
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] New release $LATEST (was $CURRENT) — deploying..."

cd "$COMPOSE_DIR"
docker compose pull
docker compose up -d

echo "$LATEST" > "$VERSION_FILE"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Deployed $LATEST successfully"
