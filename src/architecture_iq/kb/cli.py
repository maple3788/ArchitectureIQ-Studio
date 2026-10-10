"""CLI boundary for bounded KB workflows and verified local model execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .store import canonical_hash


_DEFAULT_BASE_URL = 'http://127.0.0.1:18053/v1'
_STATE_FIELDS = ('size', 'mtime_ns', 'ctime_ns', 'device', 'inode')
_PROC_ROOT = Path('/proc')


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def require_execution_host(execute: bool) -> None:
    if not execute:
        raise ValueError('Model calls and training require explicit --execute')
    if platform.system() != 'Linux':
        raise ValueError('Model calls and training require the designated Linux execution host')
    from .execution_host import execution_host_enabled

    if not execution_host_enabled():
        raise ValueError('Configure matching ARCHITECTURE_IQ_KB_EXECUTION_HOST and ARCHITECTURE_IQ_KB_AUTHORIZED_HOST privately on the execution host')


def read_runtime_lock(path: Path, config: dict, *, verify_files: bool = False) -> dict:
    """Match canonical lock identity; optionally validate attested files in place.

    File hashes originate in the prior full-file SHA256 attestations. Fresh
    stat equality checks preserve that identity without repeatedly reading
    hundreds of gigabytes. Preparation may run on a machine without the files.
    """
    fingerprint = config.get('runtime_fingerprint')
    if not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', fingerprint):
        raise ValueError('runtime_fingerprint must be a real canonical JSON SHA256 fingerprint')
    lock = _read_json(path)
    if not isinstance(lock, dict) or canonical_hash(lock) != fingerprint:
        raise ValueError('runtime lock fingerprint does not match the frozen configuration')
    for field in ('model_id', 'endpoint', 'model_path', 'chat_template_sha256'):
        if not isinstance(lock.get(field), str) or not lock[field]:
            raise ValueError(f'runtime lock requires {field}')
    if not re.fullmatch('[0-9a-f]{64}', lock['chat_template_sha256']):
        raise ValueError('runtime lock requires a SHA256 chat template identity')
    if type(lock.get('context_size')) is not int or lock['context_size'] <= 0:
        raise ValueError('runtime lock requires positive context_size')
    if lock.get('model_parameters') != config.get('model'):
        raise ValueError('runtime model parameters differ from the frozen configuration')
    if config.get('model', {}).get('name') != lock['model_id']:
        raise ValueError('runtime model does not match the frozen configuration')
    files = lock.get('file_verifications')
    if not isinstance(files, list) or not files:
        raise ValueError('runtime lock requires attested engine and weight file identities')
    for record in files:
        if (not isinstance(record, dict) or not isinstance(record.get('path'), str)
                or not re.fullmatch('[0-9a-f]{64}', str(record.get('sha256_from_attestation', '')))
                or set(record.get('current_state', {})) != set(_STATE_FIELDS)):
            raise ValueError('runtime file identity is malformed')
        if verify_files:
            stat = Path(record['path']).stat()
            current = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                       'ctime_ns': stat.st_ctime_ns, 'device': stat.st_dev, 'inode': stat.st_ino}
            if current != record['current_state']:
                raise ValueError(f'runtime file changed since attestation: {record["path"]}')
    if 'process_identity' in lock:
        process = lock['process_identity']
        if (not isinstance(process, dict)
                or type(process.get('pid')) is not int or process['pid'] <= 0
                or type(process.get('start_ticks')) is not int or process['start_ticks'] < 0
                or not re.fullmatch('[0-9a-f]{64}', str(process.get('cmdline_sha256', '')))
                or not isinstance(process.get('executable_path'), str)
                or not Path(process['executable_path']).is_absolute()):
            raise ValueError('runtime process identity is malformed')
        if verify_files:
            _verify_process(process)
    return lock


def _verify_process(expected: dict) -> None:
    process = _PROC_ROOT / str(expected['pid'])
    try:
        # comm is parenthesized and can itself contain spaces/parentheses;
        # starttime is field 22, i.e. index 19 after the closing comm delimiter.
        raw = (process / 'stat').read_text()
        pid_and_comm, delimiter, rest = raw.rpartition(')')
        fields = rest.split()
        if not delimiter or int(pid_and_comm.split(' ', 1)[0]) != expected['pid']:
            raise ValueError('invalid stat identity')
        actual = {'pid': expected['pid'], 'start_ticks': int(fields[19]),
                  'cmdline_sha256': hashlib.sha256((process / 'cmdline').read_bytes()).hexdigest(),
                  'executable_path': os.readlink(process / 'exe')}
    except (OSError, IndexError, ValueError) as exc:
        raise ValueError('runtime process is unavailable or its identity cannot be read') from exc
    if any(actual[key] != expected[key] for key in actual):
        raise ValueError('runtime process identity changed; the service may have restarted')


def verify_live_runtime(path: Path, config: dict, base_url: str) -> dict:
    """Check current process, files, and service identity at an inference boundary."""
    lock = read_runtime_lock(path, config, verify_files=True)
    if base_url.rstrip('/') != lock['endpoint'].rstrip('/'):
        raise ValueError('runtime endpoint differs from the frozen lock')
    parsed = urlsplit(base_url)
    if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('runtime endpoint must be an HTTP URL without credentials, query, or fragment')
    origin = f'{parsed.scheme}://{parsed.netloc}'

    def get(url):
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)

    health = get(origin + '/health')
    if health.get('status') != 'ok':
        raise ValueError('runtime health is not ready')
    models = get(base_url.rstrip('/') + '/models')
    if lock['model_id'] not in {item.get('id') for item in models.get('data', [])}:
        raise ValueError('runtime model is missing from /v1/models')
    props = get(origin + '/props')
    if props.get('model_alias') != lock['model_id'] or props.get('model_path') != lock['model_path']:
        raise ValueError('runtime model alias or model path changed')
    template = props.get('chat_template')
    if not isinstance(template, str) or hashlib.sha256(template.encode()).hexdigest() != lock['chat_template_sha256']:
        raise ValueError('runtime chat template changed')
    settings = props.get('default_generation_settings', {})
    if settings.get('n_ctx') != lock['context_size']:
        raise ValueError('runtime context size changed')
    model = lock['model_parameters']
    expected = {key: model[key] for key in ('temperature', 'top_p') if key in model}
    expected.update({key: value for key, value in model.get('extra', {}).items()
                     if key in {'seed', 'top_k', 'min_p', 'repeat_penalty'}})
    if any(settings.get('params', {}).get(key) != value for key, value in expected.items()):
        raise ValueError('runtime decoding defaults changed')
    return lock


def _client(base_url: str, *, runtime_lock: Path, config: dict):
    # Reuse the repository's client so transport/request semantics stay shared.
    repo = Path(__file__).resolve().parents[3]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from tools.llm_eval.llm_client import LLMClient
    client = LLMClient(base_url=base_url, api_key='local-only', timeout_s=900, max_retries=0)
    client.verify_runtime = lambda: verify_live_runtime(runtime_lock, config, base_url)
    return client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Freeze inputs without inference or training')
    prepare.add_argument('--config', type=Path, required=True)
    prepare.add_argument('--public', type=Path, required=True)
    prepare.add_argument('--private', type=Path, required=True)
    prepare.add_argument('--legacy', type=Path)
    prepare.add_argument('--legacy-rules', type=Path, help='Compiled rule document for --legacy claims')
    prepare.add_argument('--runtime-lock', type=Path, required=True)
    prepare.add_argument('--out', type=Path, required=True)
    status = commands.add_parser('status', help='Read run progress without execution')
    status.add_argument('--out', type=Path, required=True)
    for command in ('run', 'evaluate'):
        sub = commands.add_parser(command)
        sub.add_argument('--out', type=Path, required=True)
        sub.add_argument('--runtime-lock', type=Path, required=True)
        sub.add_argument('--base-url', default=None)
        sub.add_argument('--execute', action='store_true')
        if command == 'run':
            sub.add_argument('--round', type=int, required=True)
        else:
            sub.add_argument('--phase', choices=('development', 'final'), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare' and args.legacy_rules and not args.legacy:
            raise ValueError('--legacy-rules requires --legacy')
        if args.command in {'run', 'evaluate'}:
            require_execution_host(args.execute)
        from .orchestrator import prepare_run, run_round, status, evaluate_run
        if args.command == 'prepare':
            config = _read_json(args.config)
            read_runtime_lock(args.runtime_lock, config)
            legacy = _read_json(args.legacy) if args.legacy else []
            if isinstance(legacy, dict):
                legacy = legacy['claims']
            if args.legacy_rules:
                from .legacy import import_legacy_claims
                legacy = import_legacy_claims(legacy, _read_json(args.legacy_rules))
            result = prepare_run(args.out, config, _read_json(args.public), _read_json(args.private), legacy)
        elif args.command == 'status':
            result = status(args.out)
        else:
            config = _read_json(args.out / 'manifest.json')['config']
            base_url = args.base_url or os.environ.get('OPENAI_API_BASE') or _DEFAULT_BASE_URL
            verify_live_runtime(args.runtime_lock, config, base_url)
            client = _client(base_url, runtime_lock=args.runtime_lock, config=config)
            if args.command == 'run':
                result = run_round(args.out, client, None, round_index=args.round)
            else:
                result = evaluate_run(args.out, client, phase=args.phase)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, urllib.error.URLError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
