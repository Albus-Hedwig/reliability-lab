"""SQLite is the authoritative experiment record; exports are derived from it."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path):
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA busy_timeout=5000')
    try:
        yield connection
    finally:
        connection.close()


def initialize(path):
    with connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                idempotency_key TEXT UNIQUE,
                request_body TEXT NOT NULL
            );
            CREATE TABLE events (
                seq INTEGER PRIMARY KEY,
                time_ns INTEGER NOT NULL,
                scenario TEXT NOT NULL,
                actor TEXT NOT NULL,
                event TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                details TEXT NOT NULL
            );
        ''')


def record(db, scenario, actor, event, attempt=0, **details):
    own_transaction = not db.in_transaction
    if own_transaction:
        db.execute('BEGIN IMMEDIATE')
    try:
        # Sample after the write lock so timestamps follow the persisted sequence.
        db.execute(
            'INSERT INTO events(time_ns,scenario,actor,event,attempt,details) VALUES(?,?,?,?,?,?)',
            (time.monotonic_ns(), scenario, actor, event, attempt,
             json.dumps(details, sort_keys=True, allow_nan=False)),
        )
        if own_transaction:
            db.execute('COMMIT')
    except Exception:
        if own_transaction:
            db.execute('ROLLBACK')
        raise


def events(path):
    with connect(path) as db:
        result = []
        for row in db.execute('SELECT * FROM events ORDER BY seq'):
            event = dict(row)
            event['details'] = json.loads(event['details'])
            result.append(event)
        return result


def orders(path):
    with connect(path) as db:
        return [dict(row) for row in db.execute('SELECT * FROM orders ORDER BY id')]


def export_events(path, output):
    rows = events(path)
    Path(output).write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows), encoding='utf-8')
    return rows
