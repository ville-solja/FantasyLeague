#!/usr/bin/env bash
# Creates a timestamped backup of the SQLite database before a deploy.
# Usage: bash scripts/backup-db.sh [/path/to/db]
set -euo pipefail

DB="${1:-data/fantasy.db}"
BACKUP="${DB}.backup-$(date +%Y%m%d-%H%M%S)"

if [ ! -f "$DB" ]; then
    echo "ERROR: database file not found: $DB" >&2
    exit 1
fi

(umask 077 && cp "$DB" "$BACKUP")
chmod 600 "$BACKUP"
echo "Backup created: $BACKUP"
