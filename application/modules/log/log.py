# -*- coding: utf-8 -*-
""" LOGGING Module"""
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
        logger.info(message['message'])
        log_entry = LogEntry()
        log_entry.datetime = datetime.now()
        log_entry.message = message['message']
        log_entry.source = message['source']
        log_entry.affected_hosts = message['affected_hosts']
        details = []
        if message['details']:
            for detail in message['details']:
                new = DetailEntry()
                level = detail[0].lower()
                if 'error' in level.lower() or 'exception' in level.lower():
                    logger.critical(f"{detail[0]}: {detail[1]}")
                    log_entry.has_error = True
                else:
                    logger.info(f"{detail[0]}: {detail[1]}")
                new.level = level
                new.message = str(detail[1])
                details.append(new)
        log_entry.details = details
        log_entry.traceback = message['traceback']
        log_entry.save()

    def log(self, message, affected_hosts=None, source="SYSTEM", details=False):
        """ LOG Messages"""
        self._log_function({'message' : message,
                           'affected_hosts': affected_hosts,
                           'source': source,
                           'traceback': traceback.format_exc(),
                           'details': details})

    def debug(self, message):
        """Just print it out"""
        print(message)
