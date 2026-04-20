#!/bin/sh
# Container starts as root. crond needs root; gunicorn must not run as
# root, so we drop privileges to 'app' via su-exec for everything else.
set -e

echo "Starting Cron"
crond
echo "-> Done"

echo "Preconfigure..."
su-exec app /srv/cmdbsyncer sys self_configure
echo "-> Done"

echo "Container Started"
exec su-exec app "$@"

