"""
Ansible Api
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
from datetime import datetime, timedelta
from mongoengine.errors import DoesNotExist
from flask_restx import Namespace, Resource

from application.api import require_token
from application.modules.log.models import LogEntry
from application.models.host import Host
from application.models.cron import CronStats

API = Namespace('syncer')


@API.route('/logs')
class SyncerLogsApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """Return latest 100 Log Messages"""
        limit = 100
        response = []
        for entry in LogEntry.objects().order_by('-id')[:limit]:
            response.append({
                'entry_id': str(entry.id),
                'time': entry.datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': entry.message,
                'source': entry.source,
                'details': [ {'name': x.level, 'message': x.message} for x in entry.details],
                'traceback': str(entry.traceback.strip()),
                'has_error': entry.has_error,
            })
        return {
            'result': response,
        }, 200

@API.route('/services/<service_name>')
class SyncerServiceApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self, service_name):
        """Return latest Message of given Service"""
        try:
            entry = LogEntry.objects(source=service_name).order_by('-id').first()
            if not entry:
                raise IndexError
            response = {
                'entry_id': str(entry.id),
                'time': entry.datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': entry.message,
                'source': entry.source,
                'details': [ {'name': x.level, 'message': x.message} for x in entry.details],
                'traceback': str(entry.traceback.strip()),
                'has_error': entry.has_error,
            }
            return {
                'result': response,
            }, 200
        except IndexError:
            return {
                'error': "No Entry for Service Found",
            }, 404


@API.route('/cron/')
class SyncerCronApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """Return Status of Cronjob Groups"""
        try:
            response = []
            for entry in CronStats.objects:
                last_start = entry.last_start
                if last_start:
                    last_start = last_start.strftime('%Y-%m-%d %H:%M:%S')
                response.append({
                    'name': str(entry.group),
                    'last_start': last_start,
                    'next_run': entry.next_run.strftime('%Y-%m-%d %H:%M:%S'),
                    'is_running': entry.is_running,
                    'last_message': entry.last_message,
                    'has_error': entry.failure,
                })
            return {
                'result': response,
            }, 200
        except DoesNotExist:
            return {
                'error': "No Status for CronGroup Found",
            }, 404



@API.route('/hosts')
class SyncerHostsApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """Get Status of Imported Hosts"""
        ago_24h = datetime.now() - timedelta(hours=24)
        return {
            '24h_checkpoint' : str(ago_24h),
            'num_hosts': Host.objects(is_object=False).count(),
            'num_objects': Host.objects(is_object=True).count(),
            'not_updated_last_24h': Host.objects(is_object=False,
                                                 last_import_seen__lt=ago_24h).count(),
        }, 200
