#!/bin/sh
set -eu
umask 077
export PGHOST=db PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD"

backup_once() {
    # Unique temporary name; final dump appears only after successful validation.
    scratch_dump=$(mktemp /backups/.pending-XXXXXX)
    if ! pg_dump --format=custom --no-owner --no-acl --file="$scratch_dump" "$POSTGRES_DB"; then
        echo "BACKUP FAILED: pg_dump" >&2
        return 1
    fi
    if ! pg_restore --list "$scratch_dump" >/dev/null; then
        echo "BACKUP FAILED: dump verification" >&2
        return 1
    fi
    final_dump="/backups/mmc-$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$scratch_dump" | cut -c10-).dump"
    mv "$scratch_dump" "$final_dump"
    echo "Backup created: $final_dump"
}

if [ "${1:-once}" = "loop" ]; then
    while :; do
        backup_once || exit 1
        sleep 86400
    done
else
    backup_once
fi
