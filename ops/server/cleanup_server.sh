#!/usr/bin/env bash
# ==============================================================================
# ops/server/cleanup_server.sh
# Controlled cleanup script with strict safety controls, approval manifests,
# pre-removal backups, and audit logging.
# Defaults to --dry-run. Destructive execution requires --apply-approved.
# ==============================================================================
set -euo pipefail

LOG_DIR="/var/log/moltbook-alpha"
FALLBACK_LOG_DIR="/tmp/moltbook-cleanup"
BACKUP_DIR="${MOLTBOOK_CLEANUP_BACKUP_DIR:-/var/backups/moltbook-cleanup}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)

if [ -w "$LOG_DIR" ] || [ "$EUID" -eq 0 ]; then
    mkdir -p "$LOG_DIR"
    LOG_FILE="${LOG_DIR}/cleanup_${TIMESTAMP}.log"
else
    mkdir -p "$FALLBACK_LOG_DIR"
    LOG_FILE="${FALLBACK_LOG_DIR}/cleanup_${TIMESTAMP}.log"
fi
MANIFEST_FILE=""
MODE="dry-run"

# Blocked / critical root and system paths that may never be cleaned
BLOCKED_PATTERNS=(
    "^/$"
    "^/bin"
    "^/boot"
    "^/dev"
    "^/etc$"
    "^/etc/ssh"
    "^/etc/systemd$"
    "^/home$"
    "^/home/[^/]+$"
    "^/home/[^/]+/\.ssh"
    "^/lib"
    "^/proc"
    "^/root"
    "^/sbin"
    "^/sys"
    "^/usr$"
    "^/usr/bin"
    "^/usr/sbin"
    "^/var$"
    "^/var/log$"
)

# Parse CLI arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            MODE="dry-run"
            shift
            ;;
        --apply-approved)
            MODE="apply"
            shift
            ;;
        --manifest)
            MANIFEST_FILE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--dry-run | --apply-approved] [--manifest <path/to/manifest.json>]"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

log() {
    local msg="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $1"
    echo "$msg" | tee -a "$LOG_FILE"
}

log "Starting Moltbook Cleanup Tool (Mode: ${MODE})"

if [ "$MODE" = "apply" ] && [ -z "$MANIFEST_FILE" ]; then
    log "[ERROR] --apply-approved requires --manifest <path/to/manifest.json>"
    exit 1
fi

if [ "$MODE" = "apply" ] && [ ! -f "$MANIFEST_FILE" ]; then
    log "[ERROR] Manifest file not found: ${MANIFEST_FILE}"
    exit 1
fi

validate_path_safety() {
    local target="$1"
    local resolved
    resolved=$(realpath -m "$target" 2>/dev/null || true)

    if [ -z "$resolved" ]; then
        log "[REJECT] Invalid path: ${target}"
        return 1
    fi

    # Check against blocked critical paths
    for pattern in "${BLOCKED_PATTERNS[@]}"; do
        if echo "$resolved" | grep -Eq "$pattern"; then
            log "[REJECT] Path matches critical protected system pattern '${pattern}': ${resolved}"
            return 1
        fi
    done

    # Verify not a dangling or cross-filesystem symlink unless expected
    if [ -L "$target" ]; then
        local link_target
        link_target=$(readlink -f "$target" || true)
        log "[WARN] Target is a symlink pointing to: ${link_target}"
    fi

    return 0
}

SUMMARY_REMOVED=0
SUMMARY_RETAINED=0
SUMMARY_FAILED=0
SUMMARY_SKIPPED=0

execute_removal() {
    local item_type="$1"
    local item_target="$2"

    log "Evaluating target: [${item_type}] ${item_target}"

    if ! validate_path_safety "$item_target"; then
        log "[SECURITY VIOLATION] Target failed safety validation. Aborting."
        SUMMARY_FAILED=$((SUMMARY_FAILED + 1))
        return 1
    fi

    if [ "$MODE" = "dry-run" ]; then
        log "[DRY-RUN] Would inspect, back up, and remove: ${item_target}"
        SUMMARY_RETAINED=$((SUMMARY_RETAINED + 1))
        return 0
    fi

    # Mode is apply-approved
    if [ "$item_type" = "service" ]; then
        log "[ACTION] Stopping and disabling service: ${item_target}"
        if systemctl is-active --quiet "$item_target"; then
            systemctl stop "$item_target" || true
        fi
        systemctl disable "$item_target" || true
        SUMMARY_REMOVED=$((SUMMARY_REMOVED + 1))
    elif [ "$item_type" = "file" ] || [ "$item_type" = "directory" ]; then
        if [ ! -e "$item_target" ]; then
            log "[SKIP] Target does not exist on disk: ${item_target}"
            SUMMARY_SKIPPED=$((SUMMARY_SKIPPED + 1))
            return 0
        fi

        # Create pre-removal backup
        mkdir -p "$BACKUP_DIR"
        local archive_name="backup_$(basename "$item_target")_$(date -u +%Y%m%d_%H%M%S).tar.gz"
        local backup_archive="${BACKUP_DIR}/${archive_name}"
        log "[BACKUP] Creating pre-removal archive: ${backup_archive}"
        tar -czf "$backup_archive" -C "$(dirname "$item_target")" "$(basename "$item_target")" 2>&1 | tee -a "$LOG_FILE" || {
            log "[ERROR] Pre-removal backup failed for ${item_target}. Halting removal."
            SUMMARY_FAILED=$((SUMMARY_FAILED + 1))
            return 1
        }

        log "[ACTION] Removing approved target: ${item_target}"
        rm -rf "$item_target"
        SUMMARY_REMOVED=$((SUMMARY_REMOVED + 1))
    elif [ "$item_type" = "docker_container" ]; then
        log "[ACTION] Stopping and removing Docker container: ${item_target}"
        docker stop "$item_target" 2>&1 | tee -a "$LOG_FILE" || true
        docker rm "$item_target" 2>&1 | tee -a "$LOG_FILE" || true
        SUMMARY_REMOVED=$((SUMMARY_REMOVED + 1))
    else
        log "[ERROR] Unrecognized item type: ${item_type}"
        SUMMARY_FAILED=$((SUMMARY_FAILED + 1))
        return 1
    fi
}

# Main Execution Flow
if [ "$MODE" = "dry-run" ]; then
    log "Performing dry-run scan. No files or services will be altered."
    if [ -n "$MANIFEST_FILE" ]; then
        log "Scanning targets listed in manifest: ${MANIFEST_FILE}"
        # Parse manifest using Python standard library if available
        if command -v python3 >/dev/null 2>&1; then
            python3 - "$MANIFEST_FILE" << 'PYEOF' | while IFS='|' read -r itype itarget; do
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    manifest = json.load(f)
for item in manifest.get('targets', []):
    t_type = item.get('type', '')
    t_target = item.get('target', '')
    if t_type and t_target:
        print(f"{t_type}|{t_target}")
PYEOF
                execute_removal "$itype" "$itarget"
            done
        fi
    else
        log "No manifest supplied for dry-run. Recommending audit inspection."
    fi
elif [ "$MODE" = "apply" ]; then
    log "Applying approved cleanup from manifest: ${MANIFEST_FILE}"
    python3 - "$MANIFEST_FILE" << 'PYEOF' | while IFS='|' read -r itype itarget; do
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    manifest = json.load(f)
for item in manifest.get('targets', []):
    t_type = item.get('type', '')
    t_target = item.get('target', '')
    if t_type and t_target:
        print(f"{t_type}|{t_target}")
PYEOF
        execute_removal "$itype" "$itarget"
    done
fi

log "================================================================================"
log "Cleanup Summary:"
log "  Mode:     ${MODE}"
log "  Removed:  ${SUMMARY_REMOVED}"
log "  Retained: ${SUMMARY_RETAINED}"
log "  Failed:   ${SUMMARY_FAILED}"
log "  Skipped:  ${SUMMARY_SKIPPED}"
log "Log file:   ${LOG_FILE}"
log "================================================================================"
