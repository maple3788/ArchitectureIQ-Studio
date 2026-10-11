"""Self-contained proposal library; source-reported evidence is not local confirmation."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from .rule_refinement.artifacts import RuleArtifactStore

LIBRARY_ROOT = Path(__file__).resolve().parents[3] / 'configs/kb_claim_rules'


def _document(root: Path, filename: str, expected: str) -> str:
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith('.json'):
        raise ValueError('Invalid bundled document name')
    raw = (root / filename).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError('Bundled document integrity failure')
    return raw.decode('utf-8')


@lru_cache(maxsize=4)
def _compile(manifest_text: str, documents: tuple[tuple[str, str], ...]) -> list[dict]:
    manifest = json.loads(manifest_text)
    files = dict(documents)
    snapshots, items = {}, []
    with TemporaryDirectory(prefix='studio-rule-library-') as directory:
        store = RuleArtifactStore(Path(directory))
        for entry in manifest['versions']:
            filename, protocol_file = entry['file'], entry['protocol']
            document = json.loads(files[filename])
            protocol = json.loads(files[protocol_file])
            reference = protocol.get('revision_file', '')
            expected = re.search(r'sha256 ([0-9a-f]{64})', reference)
            if (protocol.get('kind') != 'pre-registration' or expected is None
                    or expected.group(1) != manifest['files'][filename]):
                raise ValueError('Confirmation protocol does not bind this proposal')
            claims = {claim['id']: claim for claim in document['claims']}
            registered = {claim['id']: claim for claim in protocol['claims']}
            for claim_id in protocol['decision_rule']['confirmatory']:
                if registered[claim_id]['rules'] != claims[claim_id]['rules']:
                    raise ValueError('Registered rules differ from proposal')
            parent = snapshots[entry['parent']] if entry['parent'] else None
            relative = 'configs/kb_claim_rules/' + filename
            source = {'kind': 'bundled', 'id': 'builtin:' + entry['id'], 'name': entry['name'],
                      'path': relative, 'file_sha256': manifest['files'][filename],
                      'created_at': 0, 'updated_at': 0}
            snapshot = store.import_rules(document, source_ref=source,
                source_document={'version_label': entry['label'], 'filename': filename,
                                 'file_sha256': manifest['files'][filename],
                                 'protocol_file': protocol_file,
                                 'protocol_sha256': manifest['files'][protocol_file]},
                confirmation_protocol=protocol,
                parent_version=parent['version'] if parent else None, parent_snapshot=parent)
            snapshots[entry['id']] = snapshot
            replicated = sum(c.get('validity_status') == 'replicated_in_scope' for c in claims.values())
            disabled = sum(c.get('inject') is False for c in claims.values())
            counts = {'rules': len(snapshot['rules']), 'active_rules': len(snapshot['rules']),
                      'retired_rules': 0, 'source_claims': len(claims), 'verified_enabled': 0,
                      'source_replicated': replicated, 'source_proposed': len(claims) - replicated,
                      'injection_disabled': disabled}
            items.append({'id': source['id'], 'kind': 'research_rules', 'name': entry['name'],
                          'summary': f'{len(claims)} 条来源规律 · {replicated} 条来源标记范围内复现；本平台尚未重新验证。',
                          'counts': counts, 'snapshot': snapshot, 'version': snapshot['version'],
                          'source': relative, 'sources': [source], 'source_count': 1, 'updated_at': 0})
    return items


def bundled_rule_inventory(root: Path | None = None) -> dict:
    """Recheck file identities each read; cache only immutable compiled content."""
    root = Path(root) if root is not None else LIBRARY_ROOT
    try:
        manifest_text = (root / 'library_manifest.json').read_text()
        manifest = json.loads(manifest_text)
        if manifest.get('schema_version') != 1:
            raise ValueError('Unsupported bundled library manifest')
        documents = tuple((name, _document(root, name, digest))
                          for name, digest in sorted(manifest['files'].items()))
        return {'items': deepcopy(_compile(manifest_text, documents)), 'warnings': []}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return {'items': [], 'warnings': [{'source_id': 'builtin:rule-library',
                'message': '内置规则文档或预注册协议未通过完整性检查，暂不提供该版本。'}]}
