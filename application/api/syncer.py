"""
Ansible Api
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
from flask_restx import Namespace, Resource
from application.api import require_token
from application.modules.log.models import LogEntry

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
