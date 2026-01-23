"""
Enpoints
"""
# pylint: disable=function-redefined
# pylint: disable=no-member
# pylint: disable=too-few-public-methods
import urllib.parse
from json.decoder import JSONDecodeError
from flask import request
from flask_httpauth import HTTPBasicAuth
from application.models.user import User
from application.helpers.get_account import get_account_by_name

from flask_restx import Namespace, Resource, fields
import requests
from application import app

API = Namespace('snow_api')


ACK_DATA = API.model('acknowledgment', {
    "QUELLE" : fields.String,
    "QUELLEID": fields.String,
    "ZIEL" : fields.String,
    "ZIELID" : fields.String,
})


AUTH = HTTPBasicAuth()

@AUTH.verify_password
def verify_password(username, password):
    """
    Verifyh AuthBasic Password
    """
    if user := User.objects.get(name=username):
        if not user.check_password(password):
            abort(401, "Invalid login")
    return True


def get_job(data):
    """
    Determine by API Data what is to do
    """
    account_name = app.config['CMK_ACCOUNT_NAME']
    config = get_account_by_name(account_name)
    source_parts = data['ZIELID'].split('|')
    if source_parts[0] == "EC":
        return "EC", source_parts[2], False, False
    job = False
    service_name = False
    if len(source_parts) == 2:
        # Host Down
        job = "host"
    elif len(source_parts) == 3:
        job = "service"
        service_name = source_parts[2]
    else:
        raise ValueError("invalid id")

    site = source_parts[0]
    host_name = source_parts[1]

    return job, site, host_name, service_name

def create_multisite_payload(data):
    """
    Create a String with URL Payloads to set ACK
    """
    account_name = app.config['CMK_ACCOUNT_NAME']
    config = get_account_by_name(account_name)
    payload = {
        '_ack_comment' : f"Ticket: {data['QUELLEID']}",
        '_secret' : config['password'],
        '_username' : config["username"],

    }
    job, site, host, svc = get_job(data)
    if job == "host":
        payload['view_name'] = 'hoststatus'
    elif job == "service":
        payload['service'] = svc
        payload['view_name'] = 'service_snow'
        #service down
    else:
        raise ValueError("invalid id")

    payload['site'] = site
    payload['host'] = host

    return "&".join([x+"="+urllib.parse.quote(y) for x, y in payload.items()])



def status_multisite():
    """
    Get Status Data from Multisite,
    also do some Hacks with ACKs etc
    """
    try:
        payload_str = create_multisite_payload(request.json)
        account_name = app.config['CMK_ACCOUNT_NAME']
        config = get_account_by_name(account_name)
        url = f"{config['address']}check_mk/view.py?output_format=json&{payload_str}"
        # The thing is that cmk not has
        # prober return status codes here,
        # so we cannot make nothing...
        response = requests.get(url, verify=app.config.get('SSL_VERIFY'), timeout=20)
        json_raw = response.json()
        data = dict(zip(json_raw[0], json_raw[1]))
        solved = True
        if 'service_state' in data:
            if data['service_state'] != "OK" and data['svc_in_downtime'] == 'no':
                solved = False
            if data['host_in_downtime'] == 'yes' or data['svc_in_downtime'] == 'yes':
                solved = True
                # Now Fake a OK State of the Service in order to have a re notification
                # in case the failure still exists after the Downtime (would not be notified
                # if failure was before downtime started
                url = f"{config['address']}check_mk/view.py?_fake_0=OK&_do_actions=yes"\
                       "&_fake_output=API+RESET"\
                       "&_do_confirm=yes&_transid=-1&{payload_str}"
                requests.get(url, verify=app.config.get('SSL_VERIFY'), timeout=20)
        else:
            if data['host_state'] != "UP" and data['host_in_downtime'] == 'no':
                solved = False
            if data['host_in_downtime'] == 'yes':
                solved = True
                url = f"{app.config.get('CMK_URL')}check_mk/view.py?_fake_0=UP&_do_actions=yes"\
                       "&_fake_output=API+RESET"\
                       "&_do_confirm=yes&_transid=-1&{payload_str}"
                requests.get(url, verify=app.config.get('SSL_VERIFY'), timeout=20)
    except JSONDecodeError:
        return {"status": str(response.text)}
    except (ValueError, IndexError) as msg:
        return {"status" :str(msg)}, 500

    return {"problem_solved" : solved}, 200



def status_ec():
    """
    Not sure what todo here
    """
    return {"problem_solved" : True}, 200

@API.route('/status/')
class StatusAPI(Resource):
    """
    Status API
    """

    @API.expect(ACK_DATA, validate=True)
    @AUTH.login_required
    def post(self):
        """
        Check if a Error still exists on a Host or Service,
        For Events: Archive the Event
        """
        try:
            job, _site, _host, _svc = get_job(request.json)
            if job == "EC":
                return status_ec()
            return status_multisite()
        except (ValueError, IndexError) as msg:
            return {"status" :str(msg)}, 500

@API.route('/ack/')
class AckApi(Resource):
    """
    Acknowledgement API
    """

    @API.expect(ACK_DATA, validate=True)
    @AUTH.login_required
    def post(self):
        """
        Set ACK on Host, Service or EC Event
        """
        try:
            data = request.json
            job, site, host, svc = get_job(data)

            account_name = app.config['CMK_ACCOUNT_NAME']
            config = get_account_by_name(account_name)

            cmk_url = config['address']
            payload = {
              "sticky": False,
              "persistent": False,
              "notify": False,
              "comment": f"Ticket : {data['QUELLEID']}",
              "host_name": host
            }
            if job == "host":
                url = f"{cmk_url}check_mk/api/1.0/domain-types/acknowledge/collections/host"
                payload['acknowledge_type'] = "host"
            elif job == "service":
                url = f"{cmk_url}check_mk/api/1.0/domain-types/acknowledge/collections/service"
                payload['acknowledge_type'] = "service"
                payload['service_description'] = svc
            elif job == "EC":
                url = \
                  f"{cmk_url}check_mk/api/1.0/objects/event_console/{site}"\
                   "/actions/update_and_acknowledge/invoke"
                # On Purpuse we overwrite the Payload here
                payload = {
                    'phase': "ack",
                    'site_id': "sa_mon_ng",
                    'change_comment':  f"Ticket: {data['QUELLEID']}",
                }

            username = config['username']
            password = config['password']
            headers = {
                'Authorization': f"Bearer {username} {password}"
            }
            requests.post(url, json=payload, verify=app.config.get('SSL_VERIFY'),
                          headers=headers, timeout=20)
        except (ValueError, IndexError) as msg:
            return {"status" :str(msg)}, 500

        return {"status" : "success"}, 200
