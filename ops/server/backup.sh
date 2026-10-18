#!/usr/bin/env bash
# ==============================================================================
# ops/server/backup.sh
# Consistent online backup of Moltbook Alpha SQLite database.
# Utilizes SQLite Online Backup API / VACUUM INTO to prevent WAL read corruption.
# Generates SHA256 checksums, enforces 0600 permissions, and prunes old snapshots.
# ==============================================================================
set -euo pipefail

BACKUP_DIR="${MOLTBOOK_BACKUP_DIR:-/var/backups/moltbook-alpha}"
DATA_DIR="${MOLTBOOK_DATA_DIR:-/var/lib/moltbook-alpha}"
DB_FILE="${DATA_DIR}/moltbook.db"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/moltbook_${TIMESTAMP}.db"
CHECKSUM_FILE="${BACKUP_FILE}.sha256"

echo "=== Moltbook Alpha Database Backup [${TIMESTAMP} UTC] ==="

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
    echo "[WARN] Database file ${DB_FILE} does not exist. Nothing to back up."
    exit 0
fi

echo "[BACKUP] Performing consistent online backup of ${DB_FILE}..."

# Perform consistent online backup via sqlite3 CLI or Python SQLite API
if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_FILE" ".backup '${BACKUP_FILE}'"
elif command -v python3 >/dev/null 2>&1; then
    python3 -c "
import sqlite3
src = sqlite3.connect('$DB_FILE')
dst = sqlite3.connect('$BACKUP_FILE')
src.backup(dst)
dst.close()
src.close()
"
else
    echo "[ERROR] Neither sqlite3 CLI nor python3 available to perform consistent backup." >&2
    exit 1
fi

chmod 600 "$BACKUP_FILE"

# Verify integrity of the newly created backup
echo "[VERIFY] Verifying integrity of backup file..."
if command -v sqlite3 >/dev/null 2>&1; then
    INTEGRITY=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" 2>&1 || true)
else
    INTEGRITY=$(python3 -c "
import sqlite3
con = sqlite3.connect('$BACKUP_FILE')
print(con.execute('PRAGMA integrity_check;').fetchone()[0])
con.close()
")
fi

if [ "$INTEGRITY" != "ok" ]; then
    echo "[ERROR] Integrity check failed on generated backup file: ${INTEGRITY}" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Generate SHA256 checksum
echo "[CHECKSUM] Generating SHA256 checksum..."
sha256sum "$BACKUP_FILE" > "$CHECKSUM_FILE"
chmod 600 "$CHECKSUM_FILE"

BACKUP_SIZE=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || stat -f%z "$BACKUP_FILE" 2>/dev/null || echo "0")
echo "[PASS] Backup created: ${BACKUP_FILE} (${BACKUP_SIZE} bytes)"
echo "[PASS] Checksum: $(cat "$CHECKSUM_FILE")"

# Prune old backups past retention policy
echo "[RETENTION] Pruning backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -type f \( -name "moltbook_*.db" -o -name "moltbook_*.sha256" \) -mtime "+${RETENTION_DAYS}" -exec rm -f {} +
echo "[DONE] Backup lifecycle complete."
