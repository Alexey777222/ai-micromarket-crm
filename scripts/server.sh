#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env.server ]; then
    echo "Run python3 scripts/init_server.py first." >&2
    exit 1
fi
exec docker compose --env-file .env.server -f compose.server.yml "$@"
