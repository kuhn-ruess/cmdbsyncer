# -*- coding: utf-8 -*-
""" LOGGING Module"""
import traceback

class Log():
    """
    General Logging Module
    """

    def __init__(self, log_func=None):
        """
        Init and Set Config
        """
        self.log_func = log_func

    def log(self, message, log_type="debug", url=None, raw=False):
        """ LOG Messages"""
        self.log_func({'message' : message,
                       'type': log_type,
                       'traceback': traceback.format_exc(),
                       'raw': raw})

    def debug(self, message):
        """Just print it out"""
        print(message)
