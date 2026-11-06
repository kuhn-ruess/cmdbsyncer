#!/bin/sh
# dcron daemonises and hands job output to sendmail / syslog, so nothing a
# cron run prints would ever reach `docker logs`. Redirect to PID 1's
# streams instead: that is what the container runtime captures and every
# log collector scrapes.
#
# Kept apart on purpose. stdout carries the log stream and nothing else,
# so a collector can scrape that stream and parse every line; stderr
# keeps whatever escapes the pipeline, an interpreter-level traceback
# for instance. `docker logs` shows both, as always.
#
# crond itself needs root, the jobs must not have it: they run plugins and
# templates. Neither user can open the streams through PID 1: it runs as
# 'app', which root may not look into without CAP_SYS_PTRACE, and the pipes
# belong to root, which 'app' may not open. So a root process of the
# entrypoint holds them, and this shell opens them from there before the
# job drops to 'app'. Dockerfile.local has no 'app' user and stays root. A
# missing su-exec is an error, not a reason to go on as root.
as_app=""
if id app >/dev/null 2>&1; then
    as_app="/sbin/su-exec app"
fi
streams="/proc/$(cat /run/cmdbsyncer_streams.pid)/fd"
$as_app /srv/cmdbsyncer cron run_jobs >> "$streams/1" 2>> "$streams/2"
