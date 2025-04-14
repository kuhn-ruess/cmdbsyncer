#!/bin/sh
echo "Preconfigure..."
/srv/cmdbsyncer sys self_configure
echo "-> Done"

echo "Container Started"
exec "$@"

