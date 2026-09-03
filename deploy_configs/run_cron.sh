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
/srv/cmdbsyncer cron run_jobs >> /proc/1/fd/1 2>> /proc/1/fd/2
