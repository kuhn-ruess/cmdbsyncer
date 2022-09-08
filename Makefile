# CMDB Syncer DEV
# .local.

cp-up:
	docker-compose -f docker-compose.yml -f docker-compose.local.yml build
	docker-compose -f docker-compose.yml -f docker-compose.local.yml -p cmdb_syncer up --force-recreate -d

cp-start:
	docker-compose -f docker-compose.yml -f docker-compose.local.yml -p cmdb_syncer start

cp-stop:
	docker-compose -f docker-compose.yml -f docker-compose.local.yml -p cmdb_syncer stop

cp-down:
	docker-compose -f docker-compose.yml -f docker-compose.local.yml -p cmdb_syncer down --rmi local --remove-orphans
