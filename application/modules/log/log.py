# -*- coding: utf-8 -*-
""" LOGGING Module"""
import logging
import traceback
from datetime import datetime
from application import logger
from application.modules.log.models import LogEntry, DetailEntry

class Log():
    """
    General Logging Module
    """

    def __init__(self, log_func=None):
        """
        Init and Set Config
        """
        self.log_func = log_func

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

        details = []
        details_struct = {}
        has_error = False
        if message['details']:
            for detail in message['details']:
                new = DetailEntry()
                level = detail[0].lower()
                if 'error' in level.lower() or 'exception' in level.lower():
                    has_error = True
                    log_entry.has_error = True
                if 'affected' in detail[0]:
                    if isinstance(detail[1], list):
                        affected_hosts.extend(detail[1])
                    else:
                        affected_hosts.append(detail[1])
                new.level = level
                new.message = str(detail[1])
                details.append(new)
                # Preserve the original (key, value) for structured
                # sinks (the enterprise JSON/ECS formatter reads this
                # from the `extra` kwarg); text sinks still see the
                # rendered summary below.
                details_struct[level] = str(detail[1])
        log_entry.affected_hosts = affected_hosts
        log_entry.details = details
        log_entry.traceback = message['traceback']
        log_entry.save()

        # Emit a single structured record instead of one line per detail.
        # The JSON formatter picks up `extra` and maps it to ECS fields;
        # the default text formatter drops these cleanly.
        logger.log(
            logging.ERROR if has_error else logging.INFO,
            message['message'],
            extra={
                'event_source': message['source'],
                'event_details': details_struct,
                'event_affected_hosts': affected_hosts,
                'event_has_error': has_error,
            },
        )

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
