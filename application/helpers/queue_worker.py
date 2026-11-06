"""
A background thread working off a queue
"""
import threading
import time


class QueueWorker:
    """
    One daemon thread for a queue, started on first use. Daemon threads die with
    the process and what is still queued would be lost, so ``drain`` waits for it.
    """

    def __init__(self, work_queue, name, exit_timeout_seconds):
        self.work_queue = work_queue
        self.name = name
        self.exit_timeout_seconds = exit_timeout_seconds
        self._lock = threading.Lock()
        self._running = False

    def start(self, target):
        """Start the thread on ``target``, unless it already runs."""
        with self._lock:
            if self._running:
                return
            thread = threading.Thread(target=target, name=self.name, daemon=True)
            thread.start()
            self._running = True

    def drain(self):
        """Block until the queue is empty or the timeout hits."""
        if not self._running:
            return
        deadline = time.monotonic() + self.exit_timeout_seconds
        while self.work_queue.unfinished_tasks > 0 and time.monotonic() < deadline:
            time.sleep(0.05)
