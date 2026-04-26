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

# Optional MCP server (SSE transport) — opt in by setting
# MCPSERVER_ENABLED=1. Authenticates per request via the same User
# accounts as the REST API; the connecting user must hold the ``mcp``
# api_role. HTTPS gate applies (set TRUSTED_PROXIES + a TLS-terminating
# proxy, or ALLOW_INSECURE_API_AUTH=True for trusted internal networks).
if [ "${MCPSERVER_ENABLED:-}" = "1" ]; then
    MCP_PORT="${MCPSERVER_PORT:-8765}"
    echo "Starting MCP server (SSE) on 0.0.0.0:${MCP_PORT}..."
    $as_app /srv/cmdbsyncer-mcp \
        --transport sse \
        --host 0.0.0.0 \
        --port "${MCP_PORT}" &
    echo "-> MCP listening at :${MCP_PORT}/sse"
fi

echo "Container Started"
exec $as_app "$@"

