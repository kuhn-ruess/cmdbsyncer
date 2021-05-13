# WIP: Sync System for Hosts to other Systems and APIs like Checkmk

Work in progress, but this tool will manage Hosts to sync them.
Main Focus is Checkmk 1.x and Checkmk 2.x, but in theory it will work with all systems
which can be accessed in some way. The System is Plugin-based and so flexible. Plugins can interact then with the local Model.

Documentation will follow.

## First Steps
 * cp application/config.py.example to application/config.py

## Requirements
 * python 3.8
  * MongoDB

## Build local Python Environemnt
  * python3 -m venv ENV
  * source ENV/bin/activate
  * pip install -r requirements.txt


## Docker
  * File will follow
