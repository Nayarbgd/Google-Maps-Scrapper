import threading
import queue
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import scrape_places


class ScrapeWorker(threading.Thread):
    """
    Runs scrape_places() in a background thread.
    Posts events to result_queue so the GUI can update live without blocking.

    Queue message types:
        ("log",      message: str)
        ("progress", current: int, total: int, place: Place)
        ("done",     places: list)
        ("error",    message: str)
        ("stopped",)
    """

    def __init__(self, search_for: str, total: int, result_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.search_for = search_for
        self.total = total
        self.queue = result_queue
        self.stop_event = stop_event
        self._places = []

    def run(self):
        self._install_log_handler()
        try:
            self._places = scrape_places(
                self.search_for,
                self.total,
                progress_callback=self._on_progress,
                stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                self.queue.put(("stopped",))
            else:
                self.queue.put(("done", self._places))
        except Exception as exc:
            self.queue.put(("error", str(exc)))
        finally:
            self._remove_log_handler()

    def _on_progress(self, current: int, total: int, place):
        self.queue.put(("progress", current, total, place))

    def _install_log_handler(self):
        self._handler = _QueueLogHandler(self.queue)
        self._handler.setFormatter(logging.Formatter("%(levelname)s — %(message)s"))
        logging.getLogger().addHandler(self._handler)

    def _remove_log_handler(self):
        logging.getLogger().removeHandler(self._handler)


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self._queue = q

    def emit(self, record):
        try:
            self._queue.put(("log", self.format(record)))
        except Exception:
            pass
