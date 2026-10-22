import concurrent.futures
import http.client
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from reliability_lab import store
from reliability_lab.server import RequestError, create_order


PAYLOAD = {'sku': 'demo-widget', 'quantity': 1}


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = Path(self.temporary.name) / 'orders.sqlite'
        store.initialize(self.db)


class OrderStoreTests(DatabaseCase):
    def test_plain_retry_creates_two_orders(self):
        first = create_order(self.db, 'plain', PAYLOAD, 'same-key')
        second = create_order(self.db, 'plain', PAYLOAD, 'same-key', 2)
        self.assertNotEqual(first['order_id'], second['order_id'])
        self.assertEqual(len(store.orders(self.db)), 2)

    def test_idempotent_retry_reuses_original_body(self):
        first = create_order(self.db, 'idempotent', PAYLOAD, 'same-key')
        second = create_order(self.db, 'idempotent', dict(reversed(list(PAYLOAD.items()))), 'same-key', 2)
        self.assertEqual(first, second)
        self.assertEqual(len(store.orders(self.db)), 1)
        self.assertEqual([event['event'] for event in store.events(self.db)],
                         ['order_committed', 'order_reused'])

    def test_conflicting_payload_leaves_one_order(self):
        create_order(self.db, 'idempotent', PAYLOAD, 'same-key')
        with self.assertRaises(RequestError) as error:
            create_order(self.db, 'idempotent', {**PAYLOAD, 'quantity': 2}, 'same-key')
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(len(store.orders(self.db)), 1)
        self.assertEqual(len(store.events(self.db)), 1)

    def test_invalid_payloads_and_keys_do_not_create_orders(self):
        for payload in [None, [], {}, {'sku': 'x', 'quantity': True},
                        {'sku': ' ', 'quantity': 1}, {'sku': 'x' * 65, 'quantity': 1},
                        {'sku': 'x', 'quantity': 0}, {'sku': 'x', 'quantity': 101},
                        {**PAYLOAD, 'extra': 1}]:
            with self.subTest(payload=payload), self.assertRaises(RequestError):
                create_order(self.db, 'idempotent', payload, 'same-key')
        for key in [None, '', 'a b', 'x' * 129, '中文']:
            with self.subTest(key=key), self.assertRaises(RequestError):
                create_order(self.db, 'idempotent', PAYLOAD, key)
        self.assertEqual(store.orders(self.db), [])

    def test_concurrent_idempotent_transactions(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            orders = list(pool.map(lambda _: create_order(self.db, 'idempotent', PAYLOAD, 'same-key'), range(16)))
        self.assertEqual(len({order['order_id'] for order in orders}), 1)
        self.assertEqual(len(store.orders(self.db)), 1)
        self.assertEqual(sum(event['event'] == 'order_committed' for event in store.events(self.db)), 1)

    def test_failed_event_write_rolls_back_order(self):
        with store.connect(self.db) as db:
            db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            create_order(self.db, 'idempotent', PAYLOAD, 'same-key')
        self.assertEqual(store.orders(self.db), [])


class OrderHTTPTests(DatabaseCase):
    def start_server(self, mode):
        stderr = tempfile.TemporaryFile(mode='w+')
        self.addCleanup(stderr.close)
        process = subprocess.Popen(
            [sys.executable, '-m', 'reliability_lab.server', '--db', str(self.db), '--mode', mode],
            cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
            stderr=stderr, text=True,
        )

        def stop():
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()

        self.addCleanup(stop)
        line = process.stdout.readline()
        if not line:
            stderr.seek(0)
            self.fail('Real HTTP server failed to start:\n' + stderr.read())
        readiness = json.loads(line)
        self.assertEqual(readiness['mode'], mode)
        self.assertEqual(readiness['pid'], process.pid)
        self.port = readiness['port']

    def request(self, payload=PAYLOAD, headers=None, path='/orders', raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            request_headers = {'Content-Type': 'application/json', 'Idempotency-Key': 'same-key', **(headers or {})}
            connection.request('POST', path, json.dumps(payload) if raw is None else raw,
                               {name: value for name, value in request_headers.items() if value is not None})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def check_dropped_response(self, mode, expected_count):
        self.start_server(mode)
        with self.assertRaises(http.client.RemoteDisconnected):
            self.request(headers={'X-Lab-Fault': 'drop-response'})
        committed = store.orders(self.db)
        self.assertEqual(len(committed), 1)
        self.assertEqual([e['event'] for e in store.events(self.db)],
                         ['request_received', 'order_committed', 'response_dropped'])
        status, order = self.request(headers={'X-Lab-Attempt': '2'})
        self.assertEqual(status, 201)
        self.assertEqual(len(store.orders(self.db)), expected_count)
        self.assertEqual(order['order_id'] == committed[0]['id'], mode == 'idempotent')
        self.assertEqual([e['event'] for e in store.events(self.db)][-3:],
                         ['request_received', 'order_reused' if mode == 'idempotent' else 'order_committed',
                          'response_started'])

    def test_plain_lost_response_then_retry(self):
        self.check_dropped_response('plain', 2)

    def test_idempotent_lost_response_then_retry(self):
        self.check_dropped_response('idempotent', 1)

    def test_payload_conflict(self):
        self.start_server('idempotent')
        self.assertEqual(self.request()[0], 201)
        self.assertEqual(self.request({**PAYLOAD, 'quantity': 2})[0], 409)
        self.assertEqual(len(store.orders(self.db)), 1)

    def test_malformed_requests_leave_no_orders(self):
        self.start_server('idempotent')
        cases = [dict(raw='{'), dict(payload={'sku': 'x', 'quantity': True}),
                 dict(headers={'Idempotency-Key': ''}),
                 dict(headers={'Idempotency-Key': None}),
                 dict(headers={'Content-Type': 'text/plain'}), dict(raw=' ' * 4097),
                 dict(headers={'X-Lab-Attempt': '0'}), dict(headers={'X-Lab-Fault': 'other'})]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(self.request(**case)[0], 400)
        self.assertEqual(self.request(path='/unknown')[0], 404)
        self.assertEqual(store.orders(self.db), [])

    def test_concurrent_requests_return_one_order(self):
        self.start_server('idempotent')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: self.request(), range(16)))
        self.assertTrue(all(status == 201 for status, _ in responses))
        self.assertEqual(len({body['order_id'] for _, body in responses}), 1)
        self.assertEqual(len(store.orders(self.db)), 1)


if __name__ == '__main__':
    unittest.main()
