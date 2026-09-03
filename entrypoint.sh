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

# No progress echoes of our own around the two steps below. crond
# reports its own start, and `sys self_configure` reports every check it
# runs — as records once a log pipeline is configured. Repeating that
# from the shell only puts lines on the container's stdout that no
# collector can parse.
# Without -L, crond logs to syslog, and there is no syslogd in this
# image — so every line it wrote was dropped, and a daemonised crond has
# its own stdout and stderr on /dev/null anyway. Log to PID 1's stderr,
# which the container runtime captures, so at least the daemon reports
# that it came up.
#
# The default level, not a louder one: crond is a C daemon and cannot
# produce a log record, so each job it announced was a plain line in the
# middle of the stream. `cron run_jobs` reports every pass itself, in
# the configured shape, including the passes with nothing to do — which
# is the same information from a side that can be parsed.
crond -L /proc/1/fd/2

$as_app /srv/cmdbsyncer sys self_configure

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

exec $as_app "$@"

