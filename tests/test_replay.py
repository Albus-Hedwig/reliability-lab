"""Synthetic parser fixtures only; real execution evidence comes from the HTTP tests."""
import json
from pathlib import Path
import tempfile
import unittest

from reliability_lab.replay import read_events, render


def fixture():
    rows = []
    for scenario, count in [('plain', 4), ('idempotent', 3)]:
        rows.extend([
            dict(seq=1, time_ns=100, scenario=scenario, actor='client', event='request_sent', attempt=1, details={}),
            dict(seq=2, time_ns=200, scenario=scenario, actor='server', event='order_committed', attempt=1,
                 details={'order_id': 7, 'order_count': count}),
            dict(seq=3, time_ns=300, scenario=scenario, actor='client', event='response_lost', attempt=1,
                 details={'error': '</script><script>alert(1)</script>'}),
        ])
    return rows


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.trace = self.root / 'events.jsonl'

    def write(self, rows):
        self.trace.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

    def test_counts_and_steps_come_from_events_and_html_escapes_script(self):
        self.write(fixture())
        result = render(self.trace, self.root)
        self.assertEqual(result, {'plain': 4, 'idempotent': 3})
        for scenario in ('plain', 'idempotent'):
            data = json.loads((self.root / (scenario + '.json')).read_text())
            expected = [row for row in fixture() if row['scenario'] == scenario]
            self.assertEqual([s['sourceEvent'] for s in data['steps']], expected)
            source = (self.root / (scenario + '.html')).read_text()
            self.assertNotIn('</script><script>alert(1)</script>', source)
            self.assertNotIn('src="http', source)
            self.assertNotIn('href="http', source)
            self.assertIn('MIT License', source)
            self.assertIn('slowed for reading', source)
        index = (self.root / 'index.html').read_text()
        self.assertIn('4 orders', index)
        self.assertIn('plain/lab.sqlite3', index)

    def test_reject_invalid_schema_sequence_and_missing_scenario(self):
        cases = []
        for key, value in [('seq', True), ('attempt', 0), ('time_ns', -1),
                           ('actor', 'unrecognized'), ('event', 'made_up'), ('details', [])]:
            rows = fixture()
            rows[0][key] = value
            cases.append(rows)
        rows = fixture()
        rows[1]['seq'] = 1
        cases.append(rows)
        rows = fixture()
        rows[1]['details']['order_count'] = 0
        cases.append(rows)
        cases.append(fixture()[:3])
        for rows in cases:
            with self.subTest(rows=rows):
                self.write(rows)
                with self.assertRaises(ValueError):
                    read_events(self.trace)

    def test_reject_invalid_and_nonfinite_json(self):
        for source in ['not json\n', '{"seq":NaN}\n', 'null\n']:
            with self.subTest(source=source):
                self.trace.write_text(source)
                with self.assertRaises(ValueError):
                    read_events(self.trace)


if __name__ == '__main__':
    unittest.main()
