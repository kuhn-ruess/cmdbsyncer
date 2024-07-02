"""
Ansible Api
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
from datetime import datetime, timedelta
from flask_restx import Namespace, Resource
from application.api import require_token
from application.modules.log.models import LogEntry
from application.models.host import Host

API = Namespace('syncer')


@API.route('/logs')
class SyncerLogsApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """Return latest 100 Log Messages"""
        limit = 100
        response = []
        for entry in LogEntry.objects()[:limit]:
            response.append({
                'entry_id': str(entry.id),
                'time': entry.datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': entry.message,
                'source': entry.source,
                'duration_sec': entry.metric_duration_sec,
                'details': [ {'level': x.level, 'message': x.message} for x in entry.details],
                'traceback': str(entry.traceback.strip()),
            })
        return {
            'entries': response,
        }, 200

@API.route('/services/<service_name>')
class SyncerLogsApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self, service_name):
        """Return latest Message of given Service"""
        try:
            entry = LogEntry.objects(source=service_name)[0]
            response = {
                'entry_id': str(entry.id),
                'time': entry.datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': entry.message,
                'source': entry.source,
                'duration_sec': entry.metric_duration_sec,
                'details': [ {'level': x.level, 'message': x.message} for x in entry.details],
                'traceback': str(entry.traceback.strip()),
            }
            return {
                'value': response,
            }, 200
        except IndexError:
            return {
                'error': "No Entry for Service Found",
            }, 404

@API.route('/hosts')
class SyncerHostsApi(Resource):
    """ Handle Actions """

    @require_token
    def get(self):
        """Get Status of Imported Hosts"""
        ago_24h = datetime.now() - timedelta(hours=24)
        return {
            'check' : str(ago_24h),
            'num_hosts': Host.objects(is_object=False).count(),
            'num_objects': Host.objects(is_object=True).count(),
            'not_updated_last_24h': Host.objects(is_object=False,
                                                 last_import_seen__lt=ago_24h).count(),
        }, 200
