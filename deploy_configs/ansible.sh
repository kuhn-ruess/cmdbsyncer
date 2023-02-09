#!/bin/bash
cd /var/www/cmdbsyncer && source /var/www/cmdbsyncer/ENV/bin/activate && flask ansible_source $1 $2
