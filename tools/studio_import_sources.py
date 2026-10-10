#!/usr/bin/env python3
"""Import the explicitly registered Studio sources and attest model health, without inference."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from architecture_iq.kb.store import write_json_atomic
from architecture_iq.studio.catalog import Catalog
from architecture_iq.studio.models import ModelRegistry

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--datasets', type=Path, required=True, help='Canonical dataset artifacts to import (read-only)')
    parser.add_argument('--frozen', type=Path, required=True, help='Root of the frozen normal/DataFlip question bundle')
    parser.add_argument('--runtime-lock', type=Path, required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:18054/v1')
    args = parser.parse_args()
    catalog = Catalog(args.state)
    pairmap = args.frozen / 'data/evals/v1_5_release_20261004/dataflip_pairs.json'
    pairs = json.loads(pairmap.read_text())
    if not isinstance(pairs, list):
        raise ValueError('Expected the frozen release pairmap list')
    sources = [(args.datasets, 'Existing canonical datasets', None)]
    for variant in ('orig', 'cf'):
        source = args.frozen / f'benchmarks/v1_5/dataflip_hard500/dataflip-hard500-{variant}-v15.json'
        sources.append((source, f'Frozen DataFlip hard500 {variant} v1.5', pairmap))
    reports = [catalog.import_source(path, name=name, pairmap_path=mapping)
               for path, name, mapping in sources]
    all_items = []
    offset = 0
    while True:
        page = catalog.list_questions(offset=offset, limit=200)
        all_items.extend(page['items'])
        offset += len(page['items'])
        if offset >= page['total'] or not page['items']:
            break
    # Original IDs can have multiple revisions: check every matching member's
    # pair lineage and split, rather than choosing an arbitrary revision.
    grouped = {}
    for item in all_items:
        grouped.setdefault((item['family'], item['id']), []).append(item)
    pair_errors = []
    for pair in pairs:
        family = pair['family']
        orig = grouped.get((family, pair['original_question']), [])
        counter = grouped.get((family, pair['counterfactual_question']), [])
        if not orig or not counter:
            pair_errors.append({'pair': pair, 'error': 'Missing pair member'})
            continue
        for left in orig:
            for right in counter:
                if not left.get('pair_id') or left.get('pair_id') != right.get('pair_id') or left.get('lineage_id') != right.get('lineage_id'):
                    pair_errors.append({'original': left['key'], 'counterfactual': right['key'],
                                        'error': 'Pair ID or lineage mismatch'})
    with sqlite3.connect(catalog.db) as connection:
        aliases = connection.execute('SELECT COUNT(*) FROM aliases').fetchone()[0]
    lock = json.loads(args.runtime_lock.read_text())
    requested = lock['model_parameters']
    registry = ModelRegistry(args.state)
    profile = registry.save({'id': 'glm-5.3-flash', 'name': 'GLM-5.3-Flash · attested runtime',
                             'model': lock['model_id'], 'base_url': args.base_url,
                             'context_size': lock['context_size'],
                             'parameters': {key: requested[key] for key in ('temperature', 'top_p', 'max_tokens', 'extra')},
                             'runtime_lock_path': str(args.runtime_lock.resolve()), 'enabled': True})
    health = registry.check(profile['id'])
    report = {'stats': catalog.stats(), 'alias_count': aliases, 'source_reports': reports,
              'families': dict(Counter(item['family'] for item in all_items)),
              'not_ready': [{'key': item['key'], 'issues': item['issues']} for item in all_items if not item['ready']],
              'pairmap': {'path': str(pairmap), 'pairs': len(pairs), 'errors': pair_errors},
              'model_health': health, 'model_revision': profile['revision']}
    write_json_atomic(args.state / 'import-report.json', report)
    print(json.dumps({**{key: report[key] for key in ('stats', 'alias_count', 'families', 'pairmap', 'model_health')},
                      'source_reports': [{key: source.get(key) for key in ('name', 'source_id', 'path', 'found', 'added', 'duplicates', 'conflicts', 'errors')}
                                         for source in reports], 'not_ready_count': len(report['not_ready'])}, ensure_ascii=False, indent=2))
    return int(bool(pair_errors or report['not_ready'] or any(source['errors'] for source in reports)))


if __name__ == '__main__':
    raise SystemExit(main())
