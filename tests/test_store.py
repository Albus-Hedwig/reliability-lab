import concurrent.futures
from pathlib import Path
import tempfile
import threading
import unittest

from reliability_lab import store


class EventOrderingTests(unittest.TestCase):
    def test_contended_event_samples_time_after_acquiring_write_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'lab.sqlite3'
            store.initialize(path)
            attempting = threading.Event()

            def waiting_writer():
                with store.connect(path) as db:
                    db.set_trace_callback(lambda sql: attempting.set() if (
                        sql == 'BEGIN IMMEDIATE' or sql.startswith('INSERT INTO events')) else None)
                    store.record(db, 'plain', 'server', 'request_received', 1)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with store.connect(path) as owner:
                    owner.execute('BEGIN IMMEDIATE')
                    future = pool.submit(waiting_writer)
                    try:
                        self.assertTrue(attempting.wait(2), 'second writer never attempted its write')
                        store.record(owner, 'plain', 'server', 'order_committed', 1, order_id=1, order_count=1)
                        owner.execute('COMMIT')
                    finally:
                        if owner.in_transaction:
                            owner.execute('ROLLBACK')
                future.result(timeout=5)
            rows = store.events(path)
            self.assertEqual([row['event'] for row in rows], ['order_committed', 'request_received'])
            self.assertLessEqual(rows[0]['time_ns'], rows[1]['time_ns'])


if __name__ == '__main__':
    unittest.main()
