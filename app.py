#!/usr/bin/env python3
import os
if 'env' not in os.environ:
    os.environ['env'] = 'devel'
from application import app
