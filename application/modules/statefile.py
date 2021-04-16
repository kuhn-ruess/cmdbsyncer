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
import datetime
from filelock import FileLock

class StateFile():

    def __init__(self, filename):
        """ Prepare Statefile """
        self.path = '/tmp/{}.py'.format(filename)
        self.lock = FileLock('/tmp/{}.lock'.format(filename))
        self.states = {}
        self.lock.acquire()
        try:
            self.states = eval(open(self.path).read())
        except:
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
        open(self.path, 'w').write(str(self.states))

    def final(self):
        self.lock.release()
