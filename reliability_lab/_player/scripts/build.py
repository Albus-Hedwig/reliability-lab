#!/usr/bin/env python3
"""Build an offline architecture animation from a validated JSON diagram."""
import argparse
import json
import time
from pathlib import Path

from validate_diagram import validate


def build(source, output=None):
    data = json.loads(Path(source).read_text(encoding='utf-8'))
    summary = validate(data)
    if output is not None:
        template = (Path(__file__).resolve().parent.parent / 'assets/player.template.html').read_text(encoding='utf-8')
        payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(template.replace('__DIAGRAM_JSON__', payload), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', '-o', type=Path, default=Path('index.html'))
    parser.add_argument('--check', action='store_true', help='Validate only; do not create HTML')
    parser.add_argument('--verify', action='store_true', help='also verify playback and export browser previews')
    parser.add_argument('--preview-dir', type=Path, help='defaults to preview next to the generated HTML')
    args = parser.parse_args()
    if args.check and args.verify:
        parser.error('--check and --verify cannot be combined')
    try:
        started = time.perf_counter()
        summary = build(args.source, None if args.check else args.output)
        summary['build_seconds'] = round(time.perf_counter() - started, 3)
        if args.verify:
            from verify_browser import verify
            report = verify(args.output, args.preview_dir or args.output.parent / 'preview')
            summary['verification'] = {key: report[key] for key in ('result', 'engine', 'elapsed_seconds')}
        print(json.dumps(summary, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError, AssertionError) as error:
        parser.exit(1, 'Build failed: ' + str(error) + '\n')

