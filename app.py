#!/usr/bin/env python3
import os
if 'config' not in os.environ:
    os.environ['config'] = 'prod'
from application import app
