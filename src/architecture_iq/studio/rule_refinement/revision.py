"""Bounded role packets and non-replaying, process-managed rule proposals."""
from __future__ import annotations

from copy import deepcopy
import json
import multiprocessing
import os
import signal
import time

from architecture_iq.kb.roles import exclusive_lock, _seal, read_receipt, role_prompt
from architecture_iq.kb.rules import PUBLIC_FIELDS, CONTROL_FIELDS, OPS
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from .artifacts import RuleArtifactStore, validate_snapshot
from .budget import BudgetExceeded, UncertainOperation
from .contracts import artifact_path, identifier
from .prediction import validate_public_case

DSL = {
    'public_fields': sorted(PUBLIC_FIELDS), 'control_fields': sorted(CONTROL_FIELDS), 'operators': sorted(OPS),
    'rule': {'scope': 'optional predicate', 'same': ['control fields equal'], 'differ': ['control fields unequal'],
             'predict': 'exactly one mode: higher_better/lower_better field with optional min_ratio; '
                        'better/worse predicates; or dominates [[field,higher|lower,optional ratio]], optional winner/loser predicates'},
    'predicate': '[field,operator,scalar], [predicates] for conjunction, or {all|any:[predicates]} or {not:predicate}',
    'operations': {'add': ['entry'], 'edit': ['rule_id','revision','entry'], 'retire':['rule_id','revision'],
                   'split':['targets (one rule_id/revision)','entries (at least two)'],
                   'merge':['targets (at least two rule_id/revision)','entries (one)']},
}


def _size(value):
    return len(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8'))


def build_revision_payload(kb, score, *, seen_case_refs, max_input_bytes, grouping):
    validate_snapshot(kb)
    if score.get('kb_version') != kb['version'] or score.get('receipt_hash') != _seal(score)['receipt_hash']:
        raise ValueError('Revision requires a matching sealed score')
    if (not isinstance(grouping,list) or len(grouping)>3 or len(set(grouping))!=len(grouping)
            or set(grouping)-{'type','rule','family'}):
        raise ValueError('Unsupported case grouping')
    index=[]
    for problem in score['problems']:
        row=score['per_question'][problem['question_ref']['key']]
        if not row['scorable']:
            raise ValueError('Material failures cannot become learning cases')
        index.append({**deepcopy(problem),'family':row['case']['question'].get('family','')})
    def group(item):
        values={'type':item['type'],'rule':str(item.get('rule_ref',{})),'family':item['family']}
        return tuple(values[k] for k in grouping)+(item['case_ref'],)
    index.sort(key=group)
    material={'kb':deepcopy(kb),'dsl':deepcopy(DSL),'total_count':len(index),'cases':[],'index_page':[]}
    if _size(material)>max_input_bytes:
        raise ValueError('KB and mandatory DSL exceed context budget')
    for item in sorted(index,key=lambda p: (p['case_ref'] in seen_case_refs,group(p))):
        row=score['per_question'][item['question_ref']['key']]
        case={'problem':item,'case':row['case'],'prediction':row['prediction'],'feedback':row['feedback']}
        trial={**material,'cases':material['cases']+[case],'index_page':material['index_page']+[item]}
        if _size(trial)<=max_input_bytes:
            material=trial
    if index and not material['cases']:
        raise ValueError('No complete case fits context budget')
    refs=[item['case_ref'] for item in material['index_page']]
    return dict(kind='revision',material=material,full_index=index,case_refs=refs,remaining_count=len(index)-len(refs),
                score_ref=score['receipt_ref'],score_hash=score['receipt_hash'],
                selection=dict(seen_case_refs=deepcopy(seen_case_refs),max_input_bytes=max_input_bytes,grouping=grouping))


def build_initial_payload(kb, cases, *, max_input_bytes):
    validate_snapshot(kb)
    material={'kb':deepcopy(kb),'dsl':deepcopy(DSL),'public_cases':[],'total_count':len(cases)}
    if _size(material)>max_input_bytes:
        raise ValueError('KB and mandatory DSL exceed context budget')
    for case in cases:
        validate_public_case(case)
        trial={**material,'public_cases':material['public_cases']+[deepcopy(case)]}
        if _size(trial)<=max_input_bytes:
            material=trial
    if cases and not material['public_cases']:
        raise ValueError('No public example fits context budget')
    return dict(kind='initialize',material=material,full_index=[c['ref'] for c in cases],case_refs=[],
                remaining_count=len(cases)-len(material['public_cases']))


def run_managed(operation, *, timeout_s, check=lambda: None):
    """A read timeout cannot stop an endless SSE stream; own and kill its process group."""
    context=multiprocessing.get_context('fork')
    receiver,sender=context.Pipe(duplex=False)
    def child():
        receiver.close()
        os.setsid()
        try:
            sender.send(('ok',operation()))
        except BaseException:
            # Provider errors may contain secrets. Private role receipts retain safe evidence.
            sender.send(('error',None))
        finally:
            sender.close()
    process=context.Process(target=child)
    end=time.monotonic()+timeout_s
    process.start()
    sender.close()
    try:
        while True:
            check()
            if time.monotonic()>=end:
                raise TimeoutError('Managed operation deadline reached')
            if receiver.poll(min(.1,max(0,end-time.monotonic()))):
                try:
                    status,value=receiver.recv()
                except EOFError:
                    raise UncertainOperation('Managed operation interrupted') from None
                check()
                if status!='ok':
                    raise UncertainOperation('Managed operation did not return a complete receipt')
                return value
    finally:
        process.join(timeout=.05)
        if process.is_alive():
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
        process.join()
        receiver.close()


def propose_patch(caller,ledger,*,attempt_id,kb,payload,initialize=False):
    identifier(attempt_id)
    validate_snapshot(kb)
    expected_kind='initialize' if initialize else 'revision'
    if payload.get('kind')!=expected_kind or payload['material'].get('kb')!=kb:
        raise ValueError('Wrong proposal material or KB version')
    root=ledger.root
    if not initialize:
        score=read_receipt(artifact_path(root,payload['score_ref'],kind='scores'))
        if payload!=build_revision_payload(kb,score,**payload['selection']):
            raise ValueError('Revision material differs from persisted score')
    else:
        if set(payload['material'])!={'kb','dsl','public_cases','total_count'}:
            raise ValueError('Initializer must use public cases only')
        for case in payload['material']['public_cases']:
            validate_public_case(case)
    role='rule_initializer' if initialize else 'rule_reviser'
    prompt=role_prompt(role,payload['material'],instruction=caller.instructions.get(role))
    reserve=len(prompt.encode('utf-8'))+caller.model.max_tokens+256
    if reserve>caller.max_context:
        raise ValueError('Role payload exceeds conservative context budget')
    request_hash=canonical_hash(dict(payload=payload,model=caller.model.to_dict(),fingerprint=caller.fingerprint,prompt=prompt))
    path=root/'proposals'/(attempt_id+'.json')
    call_id=canonical_hash(dict(role=role,key=attempt_id,round=0))
    call_path=caller.root/'calls'/(call_id+'.json')
    call_ref=str(call_path.relative_to(root))
    with exclusive_lock(root/'proposals.lock'):
        if path.exists():
            old=read_receipt(path)['proposal']
            if old['inputs_hash']!=request_hash:
                raise ValueError('Proposal inputs changed')
            return old
        existed=attempt_id in ledger.snapshot()['operations']
        ledger.reserve(attempt_id,{'model_calls':1,'tokens':reserve,**({} if initialize else {'revision_attempts':1})},inputs_hash=request_hash)
        index_ref='case_indexes/'+attempt_id+'.json'
        write_json_atomic(root/index_ref,_seal({'cases':payload['full_index'],'inputs_hash':request_hash}))
        try:
            # Recovery may read a completed response, but never re-enter an uncertain send.
            if existed:
                if not call_path.exists() or read_receipt(call_path)['status']!='complete':
                    raise UncertainOperation('Reservation has no completed role receipt')
                result=caller.call(role,payload['material'],key=attempt_id,round_index=0)
            else:
                result=run_managed(lambda:caller.call(role,payload['material'],key=attempt_id,round_index=0),
                                   timeout_s=min(900,ledger.snapshot()['remaining_seconds']),check=ledger.check_time)
        except (Exception,KeyboardInterrupt):
            actual={}
            if call_path.exists():
                actual={'tokens':read_receipt(call_path)['charged_tokens']}
            ledger.settle(attempt_id,actual=actual,receipt_ref=call_ref,outcome='uncertain')
            raise UncertainOperation('Model operation is uncertain; it will not be resent') from None
        receipt=read_receipt(call_path)
        candidate=None
        try:
            if not isinstance(result.get('case_refs'),list) or set(result['case_refs'])-set(payload['case_refs']):
                raise ValueError('Unknown case reference')
            candidate=RuleArtifactStore(root).apply_patch(kb['version'],result)
            outcome='proposed'
        except (ValueError,TypeError,KeyError):
            outcome='invalid'
        record=dict(inputs_hash=request_hash,outcome=outcome,call_ref=call_ref,index_ref=index_ref,
                    seen_case_refs=payload['case_refs'],remaining_count=payload['remaining_count'],
                    candidate_version=candidate['version'] if candidate else None)
        # Settle before publishing proposal. Replay uses the same durable response if interrupted here.
        ledger.settle(attempt_id,actual={'tokens':receipt['charged_tokens']},receipt_ref=call_ref,
                      outcome='complete' if candidate else 'invalid')
        RuleArtifactStore(root).save_proposal(attempt_id,record)
        return record
