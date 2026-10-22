import json
import tempfile
import unittest
from pathlib import Path

from reliability_lab import store
from reliability_lab.__main__ import run


class ExperimentTests(unittest.TestCase):
    def test_real_processes_http_storage_and_replay_agree(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'run'
            summary = run(output)
            self.assertEqual([s['orders'] for s in summary['scenarios']], [2, 1])
            self.assertTrue(all(s['client_pid'] != s['server_pid'] for s in summary['scenarios']))
            exported = [json.loads(line) for line in (output / 'events.jsonl').read_text().splitlines()]
            for mode in ('plain', 'idempotent'):
                actual = store.events(output / mode / 'lab.sqlite3')
                self.assertEqual(actual, [e for e in exported if e['scenario'] == mode])
                names = [e['event'] for e in actual]
                self.assertLess(names.index('order_committed'), names.index('response_dropped'))
                self.assertLess(names.index('response_dropped'), names.index('response_lost'))
                self.assertLess(names.index('response_lost'), names.index('retry_scheduled'))
                self.assertEqual(names.count('request_sent'), 2)
                self.assertEqual(names.count('response_received'), 1)
                self.assertEqual(names.count('order_committed'), 2 if mode == 'plain' else 1)
                self.assertEqual(names.count('order_reused'), 0 if mode == 'plain' else 1)
                diagram = json.loads((output / f'{mode}.json').read_text())
                self.assertEqual(len(diagram['steps']), len(actual))
                self.assertFalse(diagram['simulated'])
                self.assertTrue((output / f'{mode}.html').is_file())
            self.assertIn('idempotent.html', (output / 'index.html').read_text())

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / 'keep.txt'
            marker.write_text('keep')
            with self.assertRaises(FileExistsError):
                run(temporary)
            self.assertEqual(marker.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
