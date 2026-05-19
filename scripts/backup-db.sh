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

cp "$DB" "$BACKUP"
echo "Backup created: $BACKUP"
