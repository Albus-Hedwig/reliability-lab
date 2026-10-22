"""Loopback-only order service. Fault injection is for this experiment only."""
import argparse
import json
import os
import re
import socket
from socketserver import TCPServer
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import store


class RequestError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def create_order(db_path, mode, payload, key=None, attempt=1):
    """Commit an order and its event together; return the original result on retry."""
    if (not isinstance(payload, dict) or set(payload) != {'sku', 'quantity'}
            or not isinstance(payload['sku'], str) or not payload['sku'].strip()
            or len(payload['sku']) > 64 or type(payload['quantity']) is not int
            or not 1 <= payload['quantity'] <= 100):
        raise RequestError(400, 'Expected sku (1..64 characters) and quantity (integer 1..100)')
    if mode not in {'plain', 'idempotent'}:
        raise ValueError('Unknown mode')
    if mode == 'idempotent' and (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', key)):
        raise RequestError(400, 'A valid Idempotency-Key is required')
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    with store.connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            existing = None
            if mode == 'idempotent':
                existing = db.execute('SELECT * FROM orders WHERE idempotency_key=?', (key,)).fetchone()
            if existing is not None:
                if existing['request_body'] != body:
                    raise RequestError(409, 'Idempotency-Key was already used with another payload')
                order_id = existing['id']
                event = 'order_reused'
            else:
                result = db.execute(
                    'INSERT INTO orders(sku,quantity,idempotency_key,request_body) VALUES(?,?,?,?)',
                    (payload['sku'], payload['quantity'], key if mode == 'idempotent' else None, body),
                )
                order_id = result.lastrowid
                event = 'order_committed'
            count = db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
            store.record(db, mode, 'server', event, attempt, order_id=order_id, order_count=count)
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise
    return {'order_id': order_id, 'sku': payload['sku'], 'quantity': payload['quantity']}


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        TCPServer.server_bind(self)
        # This loopback experiment needs no reverse DNS, which can stall startup.
        self.server_name, self.server_port = self.server_address[:2]


class OrderHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def record(self, event, attempt, **details):
        with store.connect(self.server.db_path) as db:
            store.record(db, self.server.mode, 'server', event, attempt, **details)

    def respond(self, status, body):
        encoded = json.dumps(body, sort_keys=True).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        attempt = 1
        try:
            if self.path != '/orders':
                raise RequestError(404, 'Not found')
            raw_attempt = self.headers.get('X-Lab-Attempt', '1')
            if not re.fullmatch(r'[1-9][0-9]{0,8}', raw_attempt):
                raise RequestError(400, 'Invalid X-Lab-Attempt')
            attempt = int(raw_attempt)
            lengths = self.headers.get_all('Content-Length', [])
            if (self.headers.get('Transfer-Encoding') is not None or len(lengths) != 1
                    or not re.fullmatch(r'[0-9]{1,4}', lengths[0]) or not 0 < int(lengths[0]) <= 4096):
                raise RequestError(400, 'Expected Content-Length between 1 and 4096')
            if self.headers.get_content_type() != 'application/json':
                raise RequestError(400, 'Expected application/json')
            fault = self.headers.get('X-Lab-Fault')
            if fault not in {None, 'drop-response'}:
                raise RequestError(400, 'Unknown lab fault')
            try:
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]):
                    raise RequestError(400, 'Incomplete request body')
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError, TimeoutError) as exc:
                raise RequestError(400, 'Invalid JSON request body') from exc
            self.record('request_received', attempt)
            order = create_order(self.server.db_path, self.server.mode, payload,
                                 self.headers.get('Idempotency-Key'), attempt)
        except RequestError as exc:
            self.record('request_rejected', attempt, status=exc.status, error=str(exc))
            self.respond(exc.status, {'error': str(exc)})
            return
        if fault == 'drop-response':
            self.record('response_dropped', attempt, order_id=order['order_id'])
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.record('response_started', attempt, status=201, order_id=order['order_id'])
        self.respond(201, order)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--mode', required=True, choices=['plain', 'idempotent'])
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    server = LoopbackHTTPServer(('127.0.0.1', args.port), OrderHandler)
    server.db_path = args.db
    server.mode = args.mode
    print(json.dumps({'port': server.server_port, 'pid': os.getpid(), 'mode': args.mode}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
