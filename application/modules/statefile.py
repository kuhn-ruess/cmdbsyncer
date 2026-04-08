"""
Handle State File
{
    "hostname": {
        'last_update': datetime,
        'source': "ovo",
        "disabled": False,
    }
}
"""
import ast
import datetime
import json
from filelock import FileLock


def _serialize_state_value(value):
    if isinstance(value, datetime.datetime):
        return {
            "__type__": "datetime",
            "value": value.isoformat(),
        }
    return value


def _deserialize_state_value(value):
    if isinstance(value, dict) and value.get("__type__") == "datetime":
        return datetime.datetime.fromisoformat(value["value"])
    return value


def _normalize_state_entry(entry):
    return {
        key: _deserialize_state_value(value)
        for key, value in entry.items()
    }

class StateFile():

    def __init__(self, filename):
        """ Prepare Statefile """
        self.path = '/tmp/{}.json'.format(filename)
        self.lock = FileLock('/tmp/{}.lock'.format(filename))
        self.states = {}
        self.lock.acquire()
        try:
            with open(self.path, encoding="utf-8") as state_file:
                raw_states = json.load(state_file)
            self.states = {
                key: _normalize_state_entry(value)
                for key, value in raw_states.items()
            }
        except FileNotFoundError:
            self.states = {}

    def get_hosts(self, disabled=False):
        """
        Return list of hosts, either enabled or disabled
        """
        return [x for x,y in self.states.items() if y.get('disabled', False) == disabled]

    def need_update(self, hostname, hours):
        if hostname not in self.states:
            return True
        host = self.states[hostname]
        if not 'last_udpate' in host:
            return True
        if host.get('disabled'):
            return False
        timediff = datetime.datetime.now() - host['last_update']
        if divmod(timediff.total_seconds(), 3600)[0] > hours:
            return True
        return False

    def set_disabled(self, hostname, state):
        self.states.setdefault(hostname, {})
        self.states[hostname]['disabled'] = state
        self.states[hostname]['last_update'] = datetime.datetime.now()
        self._write_file()

    def set_source(self, hostname, source):
        self.states.setdefault(hostname, {})
        self.states[hostname]['source'] = source
        self.states[hostname]['last_update'] = datetime.datetime.now()
        self._write_file()

    def _write_file(self):
        serializable_state = {
            key: {
                entry_key: _serialize_state_value(entry_value)
                for entry_key, entry_value in value.items()
            }
            for key, value in self.states.items()
        }
        with open(self.path, 'w', encoding="utf-8") as state_file:
            json.dump(serializable_state, state_file)

    def final(self):
        self.lock.release()