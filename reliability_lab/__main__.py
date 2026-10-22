"""Run two real HTTP/SQLite experiments and export their recorded results."""
import argparse
import http.client
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import store


PAYLOAD = {"sku": "BOOK-001", "quantity": 1}
ORDER_KEY = "order-demo-001"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def post(port, attempt, drop=False):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    headers = {'Content-Type': 'application/json', 'Idempotency-Key': ORDER_KEY,
               'X-Lab-Attempt': str(attempt)}
    if drop:
        headers['X-Lab-Fault'] = 'drop-response'
    try:
        connection.request('POST', '/orders', json.dumps(PAYLOAD), headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def run_scenario(mode, directory):
    directory.mkdir()
    database = directory / 'lab.sqlite3'
    store.initialize(database)
    started = time.monotonic_ns()
    with (directory / 'server.log').open('w', encoding='utf-8') as log:
        server = subprocess.Popen(
            [sys.executable, '-m', 'reliability_lab.server', '--db', str(database),
             '--mode', mode, '--port', '0'],
            cwd=Path(__file__).resolve().parent.parent,
            stdout=subprocess.PIPE, stderr=log, text=True,
        )
        try:
            ready = queue.Queue()
            threading.Thread(target=lambda: ready.put(server.stdout.readline()), daemon=True).start()
            try:
                line = ready.get(timeout=5)
            except queue.Empty as error:
                raise RuntimeError(f'{mode}: server startup timed out; see {directory / "server.log"}') from error
            require(bool(line), f'{mode}: server did not start; see {directory / "server.log"}')
            address = json.loads(line)
            require(address['pid'] == server.pid, 'server readiness PID mismatch')
            require(address['mode'] == mode, 'server mode mismatch')
            require(server.pid != os.getpid(), 'HTTP service must run in a separate process')
            with store.connect(database) as db:
                store.record(db, mode, 'client', 'request_sent', 1)
            try:
                post(address['port'], 1, drop=True)
            except (http.client.RemoteDisconnected, ConnectionResetError) as error:
                with store.connect(database) as db:
                    store.record(db, mode, 'client', 'response_lost', 1, error=type(error).__name__)
            else:
                raise RuntimeError('fault injection failed: first request unexpectedly returned a response')
            before_retry = store.orders(database)
            require(len(before_retry) == 1, 'first order was not durably committed before retry')
            require(any(e['event'] == 'response_dropped' for e in store.events(database)),
                    'disconnect was not the intended after-commit fault')
            with store.connect(database) as db:
                store.record(db, mode, 'client', 'retry_scheduled', 2)
                store.record(db, mode, 'client', 'request_sent', 2)
            status, body = post(address['port'], 2)
            require(status == 201 and type(body.get('order_id')) is int, 'retry did not return an order')
            with store.connect(database) as db:
                store.record(db, mode, 'client', 'response_received', 2, status=status, order_id=body['order_id'])
            rows = store.orders(database)
            expected = 2 if mode == 'plain' else 1
            require(len(rows) == expected, f'{mode}: expected {expected} orders, found {len(rows)}')
            require(body['order_id'] == rows[-1]['id'], 'response and persisted order disagree')
            if mode == 'idempotent':
                require(body['order_id'] == before_retry[0]['id'], 'retry did not reuse the original order')
            return {
                'mode': mode, 'client_pid': os.getpid(), 'server_pid': server.pid,
                'port': address['port'], 'attempts': 2, 'orders': len(rows),
                'order_ids': [row['id'] for row in rows], 'response_order_id': body['order_id'],
                'elapsed_ms': round((time.monotonic_ns() - started) / 1_000_000, 3),
                'checks_passed': True,
            }
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=3)
            server.stdout.close()


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    scenarios = []
    recorded = []
    for mode in ('plain', 'idempotent'):
        directory = output / mode
        scenarios.append(run_scenario(mode, directory))
        recorded.extend(store.export_events(directory / 'lab.sqlite3', directory / 'events.jsonl'))
    (output / 'events.jsonl').write_text(
        ''.join(json.dumps(event, sort_keys=True) + '\n' for event in recorded), encoding='utf-8')
    summary = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
               'fault': 'connection_closed_after_commit_before_http_response', 'scenarios': scenarios}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    from .replay import render
    render(output / 'events.jsonl', output)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('runs') / datetime.now().strftime('%Y%m%d-%H%M%S-%f'),
                        help='new output directory; existing directories are never overwritten')
    args = parser.parse_args()
    try:
        summary = run(args.output)
    except (OSError, ValueError, RuntimeError, http.client.HTTPException) as error:
        parser.exit(1, f'Experiment failed: {error}\n')
    for scenario in summary['scenarios']:
        print(f"{scenario['mode']:12} attempts={scenario['attempts']} orders={scenario['orders']} "
              f"response_order_id={scenario['response_order_id']}")
    print(f'Replay: {args.output.resolve() / "index.html"}')


if __name__ == '__main__':
    main()
