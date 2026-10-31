#!/bin/sh
set -e
if [ "${1:-}" = "gunicorn" ]; then
    if [ "${RUN_LOCAL_MIGRATIONS:-0}" = "1" ] && [ "${MMC_ENV:-local}" = "local" ]; then
        python manage.py migrate --noinput
    fi
    # Migrations are an explicit release step. Never seed/reset on restart.
    python manage.py check
    python manage.py migrate --check
    if [ "${MMC_ENV:-local}" = "production" ]; then
        python manage.py check_pilot_ready
    fi
    python manage.py collectstatic --noinput
fi
exec "$@"
