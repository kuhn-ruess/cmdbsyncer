#!/bin/sh
# Container starts as root. crond needs root; gunicorn must not run as
# root, so we drop privileges to 'app' via su-exec for everything else.
# Dockerfile.local doesn't install su-exec and has no 'app' user, so we
# fall back to running as root in that case (fine for local dev).
set -e

if command -v su-exec >/dev/null 2>&1; then
    as_app="su-exec app"
else
    as_app=""
fi

echo "Starting Cron"
crond
echo "-> Done"

echo "Preconfigure..."
$as_app /srv/cmdbsyncer sys self_configure
echo "-> Done"

echo "Container Started"
exec $as_app "$@"

