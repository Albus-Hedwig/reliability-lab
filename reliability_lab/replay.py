"""Convert observed lab events to offline architecture replays."""
import html
import json
from pathlib import Path
import subprocess
import sys


SCENARIOS = ('plain', 'idempotent')
EVENTS = {
    'request_sent': ('client', 'request', 'SENT'),
    'response_lost': ('client', 'drop', 'LOST'),
    'retry_scheduled': ('client', None, 'RETRY'),
    'response_received': ('client', 'response', 'RECEIVED'),
    'request_received': ('server', 'request', 'RECEIVED'),
    'order_committed': ('server', 'write', 'COMMITTED'),
    'order_reused': ('server', 'read', 'REUSED'),
    'response_dropped': ('server', 'drop', 'DROPPED'),
    'response_started': ('server', 'response', 'SENDING'),
    'request_rejected': ('server', None, 'REJECTED'),
}


def _invalid_constant(value):
    raise ValueError('Non-finite JSON number: ' + value)


def read_events(path):
    """Validate each scenario independently: their SQLite sequences restart."""
    groups = {name: [] for name in SCENARIOS}
    for line_number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        try:
            row = json.loads(line, parse_constant=_invalid_constant)
            if not isinstance(row, dict):
                raise ValueError('event must be an object')
            for field in ('seq', 'time_ns', 'attempt'):
                if type(row.get(field)) is not int or row[field] < (0 if field == 'time_ns' else 1):
                    raise ValueError(field + ' must be a positive integer (time_ns may be zero)')
            if row.get('scenario') not in SCENARIOS:
                raise ValueError('unknown scenario')
            event = row.get('event')
            if not isinstance(event, str) or event not in EVENTS:
                raise ValueError('unknown event')
            if row.get('actor') != EVENTS[event][0]:
                raise ValueError('actor does not match event')
            details = row.get('details')
            if not isinstance(details, dict):
                raise ValueError('details must be an object')
            if event in ('order_committed', 'order_reused'):
                for field in ('order_id', 'order_count'):
                    if type(details.get(field)) is not int or details[field] < 1:
                        raise ValueError(event + ' requires a positive ' + field)
            if event in ('response_started', 'response_received'):
                if type(details.get('status')) is not int or not 100 <= details['status'] <= 599:
                    raise ValueError(event + ' requires an HTTP status')
                if type(details.get('order_id')) is not int or details['order_id'] < 1:
                    raise ValueError(event + ' requires a positive order_id')
            previous = groups[row['scenario']]
            if previous and (row['seq'] <= previous[-1]['seq'] or row['time_ns'] < previous[-1]['time_ns']):
                raise ValueError('scenario sequence/time is out of order')
            previous.append(row)
        except (ValueError, TypeError) as error:
            raise ValueError(f'{path}:{line_number}: {error}') from error
    for scenario, rows in groups.items():
        if not rows:
            raise ValueError('missing scenario: ' + scenario)
        if not any(row['event'] in ('order_committed', 'order_reused') for row in rows):
            raise ValueError('no observed order count for scenario: ' + scenario)
    return groups


def diagram(scenario, rows):
    nodes = [
        {'id': 'client', 'title': 'CLIENT', 'color': 'cyan', 'bounds': [40, 180, 280, 300],
         'subtitle': 'Real HTTP requests', 'state': 'IDLE', 'operation': 'No event observed yet'},
        {'id': 'service', 'title': 'SERVICE', 'color': 'blue', 'bounds': [460, 180, 310, 300],
         'subtitle': 'Loopback order service', 'state': 'IDLE', 'operation': 'No event observed yet'},
        {'id': 'database', 'title': 'SQLITE', 'color': 'green', 'bounds': [920, 180, 280, 300],
         'subtitle': 'Persistent order rows', 'state': 'UNKNOWN', 'operation': 'No count observed yet'},
    ]
    routes = []
    for name, source, target, y, label, color in (
        ('request', 'client', 'service', 245, 'request', 'cyan'),
        ('drop', 'service', 'client', 315, 'close / lost', 'red'),
        ('response', 'service', 'client', 385, 'response', 'blue'),
        ('write', 'service', 'database', 245, 'commit', 'green'),
        ('read', 'database', 'service', 385, 'reuse', 'purple'),
    ):
        positions = {'client': (40, 320), 'service': (460, 770), 'database': (920, 1200)}
        forward = positions[source][0] < positions[target][0]
        start = positions[source][1 if forward else 0]
        end = positions[target][0 if forward else 1]
        routes.append({'id': name, 'source': source, 'target': target, 'color': color,
                       'points': [[start, y], [end, y]], 'label': label,
                       'labelAt': [min(start, end) + 12, y - 16]})
    steps = []
    count = None
    for row in rows:
        event = row['event']
        actor, route, state = EVENTS[event]
        node = 'client' if actor == 'client' else 'service'
        elapsed_ns = row['time_ns'] - rows[0]['time_ns']
        if event in ('order_committed', 'order_reused'):
            count = row['details']['order_count']
        states = {node: {'state': state, 'operation': event.replace('_', ' '),
                         'footer': f"Attempt {row['attempt']} · seq {row['seq']}"}}
        if count is not None:
            states['database'] = {'state': f'ROWS: {count}', 'operation': f'{count} orders observed',
                                  'footer': 'Count from recorded persistence event'}
        steps.append({
            'id': f"event-{row['seq']}", 'label': f"#{row['seq']} {event.replace('_', ' ').upper()}",
            'shortLabel': f"#{row['seq']}", 'duration': 1.5,
            'description': f"Observed seq {row['seq']} · +{elapsed_ns / 1_000_000:.6f} ms ({elapsed_ns} ns) · "
                           f"attempt {row['attempt']} · {actor}.{event}\n"
                           + json.dumps(row['details'], ensure_ascii=False, sort_keys=True),
            'activeNodes': [node] + (['database'] if event in ('order_committed', 'order_reused') else []),
            'activeRoutes': [route] if route else [], 'nodeStates': states,
            'sourceEvent': row,
        })
    return {
        'version': 1, 'title': 'RESPONSE LOSS LAB · ' + scenario.upper(), 'simulated': False,
        'subtitle': 'Observed educational fault injection · playback slowed for reading, not measured runtime',
        'windowTitle': 'reliability-lab / observed-events.jsonl',
        'canvas': {'width': 1240, 'height': 550},
        'nodes': nodes, 'routes': routes, 'steps': steps,
    }


def render(trace_path: Path, output_dir: Path):
    groups = read_events(trace_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for scenario, rows in groups.items():
        data = diagram(scenario, rows)
        source = output_dir / (scenario + '.json')
        source.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / '_player/scripts/build.py'),
             str(source), '--output', str(output_dir / (scenario + '.html'))],
            text=True, capture_output=True, check=False,
        )
        if result.returncode:
            raise ValueError('Replay build failed: ' + result.stderr.strip())
        counts[scenario] = next(row['details']['order_count'] for row in reversed(rows)
                                if row['event'] in ('order_committed', 'order_reused'))
    cards = ''.join(
        f'<article><h2>{html.escape(scenario.title())}</h2><p><strong>{counts[scenario]} orders</strong> '
        f'last observed in SQLite.</p><a href="{scenario}.html">Open interactive replay →</a>'
        f'<p><a href="{scenario}.json">Diagram data</a> · '
        f'<a href="{scenario}/lab.sqlite3">SQLite database</a></p></article>'
        for scenario in SCENARIOS
    )
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reliability Lab · Response lost, order committed</title>
<style>body{background:#101820;color:#e7edf2;font:18px/1.6 system-ui,sans-serif;max-width:960px;margin:64px auto;padding:24px}
h1{font-size:clamp(32px,6vw,56px);line-height:1.1}a{color:#7dd3fc}main{display:flex;flex-wrap:wrap;gap:24px}
article{flex:1;min-width:250px;border:1px solid #43515f;border-radius:12px;padding:24px}strong{color:#b5eea5}
small{color:#b5c1cc}a:focus-visible{outline:3px solid #fff;outline-offset:4px}</style>
<small>RELIABILITY LAB / REAL HTTP + SQLITE</small><h1>Response lost.<br>Order committed.</h1>
<p>The service commits an order, deliberately closes the connection before responding, and receives a retry.
Compare the observed persistence counts below.</p><main>''' + cards + '''</main>
<p>Educational fault injection on loopback; these are observed lab events, not production telemetry.
Each replay step corresponds to one recorded event and shows its sequence and measured relative timestamp.
Playback holds each event for 1.5 seconds, slowed for reading, not measured runtime.
“Response started” means the server began writing; only the client’s “response received” confirms receipt.</p>
<p><a href="events.jsonl">Raw event log</a> · <a href="summary.json">Run summary</a></p></html>'''
    (output_dir / 'index.html').write_text(page, encoding='utf-8')
    return counts
