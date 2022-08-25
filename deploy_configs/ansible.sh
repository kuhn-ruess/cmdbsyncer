#!/bin/bash
cd /var/www/cmdb-syncer && source /var/www/cmdb-syncer/ENV/bin/activate && flask ansible_source $1 $2
