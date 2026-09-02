# -*- coding: utf-8 -*-
""" LOGGING Module"""
import logging
import traceback
from datetime import datetime
from application import logger
from application.modules.log.models import LogEntry, DetailEntry

# The external sink. Every entry written through this module goes to the
# 'debug' logger (human console, muted by default) *and* here, so an admin
# only has to point this logger's handler at their log pipeline — syslog,
# a file, a collector — via LOGGING in local_config.py.
syslog_logger = logging.getLogger('syslog')

class Log():
    """
    General Logging Module
    """

    def __init__(self, log_func=None):
        """
        Init and Set Config
        """
        self.log_func = log_func

    @staticmethod
    def _collect_details(raw_details, affected_hosts):
        """
        Turn the caller's (key, value) pairs into the DetailEntry list for
        the Log view plus a dict of the same data for structured sinks
        (the enterprise JSON/ECS formatter reads it from the `extra`
        kwarg). Hostnames named by an 'affected' key are appended to
        `affected_hosts` in place. Returns (details, struct, has_error).
        """
        details = []
        struct = {}
        has_error = False
        for detail in raw_details or []:
            new = DetailEntry()
            level = detail[0].lower()
            if 'error' in level or 'exception' in level:
                has_error = True
            if 'affected' in detail[0]:
                if isinstance(detail[1], list):
                    affected_hosts.extend(detail[1])
                else:
                    affected_hosts.append(detail[1])
            new.level = level
            new.message = str(detail[1])
            details.append(new)
            # Keys repeat routinely — an export appends one ('error', …)
            # per failed host — so repeats collect into a list instead of
            # overwriting each other down to the last one.
            if level in struct:
                if not isinstance(struct[level], list):
                    struct[level] = [struct[level]]
                struct[level].append(str(detail[1]))
            else:
                struct[level] = str(detail[1])
        return details, struct, has_error

    def _log_function(self, message):
        """
        Write entries do db
        """
        log_entry = LogEntry()
        log_entry.datetime = datetime.now()
        log_entry.message = message['message']
        log_entry.source = message['source']
        affected_hosts = []
        if message['affected_hosts']:
            affected_hosts += message['affected_hosts']

        details, details_struct, has_error = self._collect_details(
            message['details'], affected_hosts)
        log_entry.has_error = has_error
        log_entry.affected_hosts = affected_hosts
        log_entry.details = details
        log_entry.traceback = message['traceback']
        log_entry.save()

        # Emit a single structured record instead of one line per detail.
        # The JSON formatter picks up `extra` and maps it to ECS fields;
        # the default text formatter drops these cleanly.
        level = logging.ERROR if has_error else logging.INFO
        extra = {
            'event_source': message['source'],
            'event_details': details_struct,
            'event_affected_hosts': affected_hosts,
            'event_has_error': has_error,
        }
        # The traceback is stored on the log entry, so a structured sink
        # should carry it too. Outside an except block `format_exc()`
        # returns 'NoneType: None' — only a real one is worth shipping.
        if message['traceback'] and not message['traceback'].startswith('NoneType'):
            extra['event_traceback'] = message['traceback']
        for target in (logger, syslog_logger):
            target.log(level, message['message'], extra=extra)

        # Fan the entry into the notification dispatcher directly.
        # We do *not* go through Python logging because the syncer's
        # 'debug' logger level is configurable and routinely set high
        # enough to drop info/error records before any handler sees
        # them — the entry would be in the Log view but never trigger
        # a notification.
        try:
            from application.helpers.notification_dispatch import (  # pylint: disable=import-outside-toplevel
                dispatch_log_entry,
            )
            dispatch_log_entry(
                message['message'], message['source'],
                has_error, details_struct, affected_hosts,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def log(self, message, affected_hosts=None, source="SYSTEM", details=None):
        """ LOG Messages"""
        self._log_function({'message' : message,
                           'affected_hosts': affected_hosts,
                           'source': source,
                           'traceback': traceback.format_exc(),
                           'details': details})

    def debug(self, message):
        """Just print it out"""
        print(message)
