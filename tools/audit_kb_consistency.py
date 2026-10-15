#!/usr/bin/env python3
"""Audit frozen loop claims on the authorized server; write a separate report.

Never changes the experiment, original claims, receipts or GT. Resumable model
cache and reports belong in private runtime storage, not in source control.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',required=True,type=Path)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--source-identity',required=True)
    args=parser.parse_args()
    sys.path[:0]=[str(args.runtime/'src'),str(args.runtime/'tools')]
    # Policy and adapter are the reviewed files alongside this executable.
    from kb_consistency_runtime import budget_context,require_authorized_execution
    import importlib.util
    policy_path=Path(__file__).with_name('claim_consistency.py')
    if not policy_path.exists():
        policy_path=Path(__file__).resolve().parents[1]/'src/architecture_iq/kb/claim_consistency.py'
    spec=importlib.util.spec_from_file_location('audit_claim_consistency',policy_path)
    policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
    require_authorized_execution()
    from kb_loop.qwen import ReplicaPool,read_api_key,extract_json
    import yaml
    cfg=yaml.safe_load((args.run/'config.yaml').read_text())
    claims=json.loads((args.run/'claims.json').read_text())['claims']
    before=policy.digest(claims)
    context=budget_context(args.runtime,cfg)
    q=cfg.get('proposer') or cfg['qwen']
    args.output.parent.mkdir(parents=True,exist_ok=True)
    pool=ReplicaPool(q['base_urls'],q['model'],args.output.parent/'model_cache',timeout_s=q['timeout_s'],
        max_tokens=q.get('max_tokens',0),concurrency=q['concurrency'],api_key=read_api_key(q.get('api_key_file')),
        extra_params=q.get('extra_params'),send_temperature=q.get('send_temperature',True),
        thinking_toggle=q.get('thinking_toggle',True),stream=q.get('stream',False))
    report={'schema_version':1,'source_identity':args.source_identity,'checker_version':policy.CHECKER_VERSION,
            'source_claims_hash':before,'started_at':time.time(),'budget_context':context,'claims':{}}
    def save():
        report['summary']=dict(Counter(item['audit']['status'] for item in report['claims'].values()))
        report['completed']=len(report['claims']);report['total']=len(claims);report['updated_at']=time.time()
        tmp=args.output.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False));tmp.replace(args.output)
    def check(pair):
        cid,claim=pair
        try:
            response=pool.complete(policy.audit_messages(claim,context),q.get('check_temperature',0),
                                   f'{policy.CHECKER_VERSION}:{policy.claim_hash(claim)}:{policy.digest(context)}')
            value=extract_json(response)
        except Exception:
            value=None
        try:
            audit=policy.validate_audit(claim,context,value)
        except (ValueError,TypeError,KeyError,IndexError,AttributeError):
            audit=policy.validate_audit(claim,context,None)
        return cid,{'version':claim['version'],'claim_hash':policy.claim_hash(claim),'audit':audit}
    save()
    with ThreadPoolExecutor(max_workers=q['concurrency']) as executor:
        futures=[executor.submit(check,pair) for pair in claims.items()]
        for future in as_completed(futures):
            cid,item=future.result();report['claims'][cid]=item;save()
    assert policy.digest(json.loads((args.run/'claims.json').read_text())['claims'])==before,'Source changed during audit'
    report['finished_at']=time.time();report['source_unchanged']=True;save()
    print(json.dumps({'completed':report['completed'],'summary':report['summary'],'source_unchanged':True}))

if __name__=='__main__':main()
