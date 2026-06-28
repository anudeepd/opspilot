#!/bin/bash
# DBS_DAILY_ARCHIVE.sh — Daily archive and compression job
#
# TWS JOBCMD: /bin/bash /jobs/DBS_DAILY_ARCHIVE.sh --date YYYY-MM-DD
#
# Known issues (pre-fix):
#   - Deployment pipeline does not apply chmod +x → RC=126 Permission denied
#   - Script edited on Windows workstations → CRLF line endings → bash syntax error
#   - Helper script path hardcoded to /opt/tws/utils/ → breaks after infra migration
#
# Fix (INC-20241101-C001):
#   - Ansible playbook updated with mode=0755 for all .sh files
#   - Added dos2unix step to CI pipeline for .sh files
#   - Updated helper path to /jobs/utils/

set -e
set -o pipefail

ARCHIVE_BASE="/data/archive"
COMPRESS_SCRIPT="/jobs/utils/compress_and_move.sh"
LOG_RETENTION_DAYS=30
DATE=""

usage() {
    echo "Usage: $0 --date YYYY-MM-DD"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --date)
            DATE="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            ;;
    esac
done

if [[ -z "$DATE" ]]; then
    usage
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "Starting DBS_DAILY_ARCHIVE for date: $DATE"

# Step 1: Verify helper script exists and is executable
# KNOWN ISSUE (pre-fix): this check was absent — script just called helper directly
if [[ ! -x "$COMPRESS_SCRIPT" ]]; then
    log "ERROR: $COMPRESS_SCRIPT is not executable or does not exist"
    log "Fix: chmod +x $COMPRESS_SCRIPT"
    exit 126
fi

# Step 2: Create archive directory for this date
ARCHIVE_DIR="${ARCHIVE_BASE}/${DATE}"
mkdir -p "$ARCHIVE_DIR"
log "Archive directory: $ARCHIVE_DIR"

# Step 3: Find files to archive
SOURCE_DIR="/data/jobs/output/${DATE}"
if [[ ! -d "$SOURCE_DIR" ]]; then
    log "WARNING: No output directory found for $DATE: $SOURCE_DIR"
    exit 0
fi

FILE_COUNT=$(find "$SOURCE_DIR" -type f | wc -l)
log "Found $FILE_COUNT files to archive in $SOURCE_DIR"

# Step 4: Call compression helper
# KNOWN ISSUE (pre-fix): called as ./compress_and_move.sh (relative path + no chmod check)
log "Calling compression helper: $COMPRESS_SCRIPT"
"$COMPRESS_SCRIPT" --source "$SOURCE_DIR" --dest "$ARCHIVE_DIR" --format gzip

log "Compression complete. Files moved to $ARCHIVE_DIR"

# Step 5: Clean up old logs
log "Cleaning logs older than $LOG_RETENTION_DAYS days"
find /var/log/tws -name "*.log" -mtime +"$LOG_RETENTION_DAYS" -delete
log "Log cleanup complete"

log "DBS_DAILY_ARCHIVE completed successfully for $DATE"
exit 0
