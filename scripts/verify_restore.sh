#!/bin/sh
# Restore a dump into a NEW temporary database. Never touches the live database.
set -eu
cd "$(dirname "$0")/.."
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "Usage: sh scripts/verify_restore.sh backups/EXACT_FILE.dump" >&2
    exit 1
fi
dump_file=$1
verify_db="verify_$(date -u +%Y%m%d%H%M%S)_$$"
sh scripts/server.sh exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$verify_db"
trap 'sh scripts/server.sh exec -T db sh -c '\''dropdb -U "$POSTGRES_USER" "$1"'\'' sh "$verify_db"' EXIT
sh scripts/server.sh exec -T db sh -c \
    'pg_restore -U "$POSTGRES_USER" --dbname="$1" --single-transaction --exit-on-error --no-owner --no-acl' \
    sh "$verify_db" < "$dump_file"
sh scripts/server.sh exec -T db sh -c \
    'psql -U "$POSTGRES_USER" --dbname="$1" -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) AS sales FROM core_sale;"' \
    sh "$verify_db"
echo "Restore verified in temporary database; live data unchanged."
