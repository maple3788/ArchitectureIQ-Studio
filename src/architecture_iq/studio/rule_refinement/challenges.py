"""Parent-bound canonical generation. No training or question-selection implementation."""
from __future__ import annotations

import argparse
from copy import deepcopy
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from architecture_iq.kb.roles import _seal, exclusive_lock, read_receipt
from architecture_iq.kb.store import canonical_hash, write_json_atomic
from architecture_iq.studio.catalog import Catalog
from architecture_iq.studio.dataset_generation import completed_generation_result
from architecture_iq.studio.generation import validate_generation, _INPUT_FIELDS
from architecture_iq.studio.jobs import JobStore, read, process_stamp
from .budget import BudgetLedger, BudgetExceeded, UncertainOperation
from .contracts import PROTOCOL


class RefinementStopped(RuntimeError):
    pass


def prepare_challenge(config, *, attempt_index, questions_per_batch):
    if type(attempt_index) is not int or attempt_index<1 or type(questions_per_batch) is not int or questions_per_batch<1:
        raise ValueError('Positive attempt and actual question count required')
    base=validate_generation(config)
    if base['split']!='discovery' or 'dataset_target' in base:
        raise ValueError('Challenges require discovery data without automatic Dataset attachment')
    paired=base['mode']=='paired'
    if paired and questions_per_batch%2:
        raise ValueError('A paired challenge needs an even actual question count')
    request={k:deepcopy(v) for k,v in base.items() if k in _INPUT_FIELDS}
    request.update(num_questions=questions_per_batch//2 if paired else questions_per_batch,
                   seed=base['seed']+(attempt_index-1)*questions_per_batch)
    return validate_generation(request)


def _parent_root(jobs,parent_id):
    return jobs.directory(parent_id)/'refinement'


def bind_challenge(jobs, *, parent_id, attempt_index, frozen_config, ledger):
    parent=jobs.definition(parent_id)
    if parent['config'].get('protocol')!=PROTOCOL or ledger.root.resolve()!=_parent_root(jobs,parent_id).resolve():
        raise ValueError('Wrong parent protocol or budget root')
    expected=prepare_challenge(parent['config']['generation'],attempt_index=attempt_index,
                               questions_per_batch=ledger.limits['questions_per_batch'])
    if expected!=frozen_config:
        raise ValueError('Challenge differs from frozen generation configuration')
    operation=f'challenge-{attempt_index}'
    identity=canonical_hash({'parent':parent['definition_hash'],'attempt_index':attempt_index,'config':frozen_config})
    path=ledger.root/'challenges'/(operation+'.json')
    with exclusive_lock(ledger.root/'challenges.lock'):
        if path.exists():
            binding=read_receipt(path)
            if binding['inputs_hash']!=identity:
                raise ValueError('Challenge attempt inputs changed')
            read_parent_binding(jobs,binding['child_id'])
            return binding
        ledger.reserve(operation,dict(generation_attempts=1,new_questions=frozen_config['requested_question_count'],
                                      candidate_seed_runs=frozen_config['candidate_seed_runs']),inputs_hash=identity)
        child=jobs.create('generation',frozen_config,idempotency_key=f'{parent_id}:challenge:{attempt_index}')
        if child['source_fingerprint']!=parent['source_fingerprint']:
            raise ValueError('Source changed between parent and generation child')
        binding=_seal(dict(protocol=PROTOCOL,parent_id=parent_id,child_id=child['id'],attempt_index=attempt_index,
                           parent_definition_hash=parent['definition_hash'],child_definition_hash=child['definition_hash'],
                           operation_key=operation,inputs_hash=identity,deadline=ledger.snapshot()['deadline']))
        write_json_atomic(jobs.directory(child['id'])/'refinement_parent.json',binding)
        write_json_atomic(path,binding)
        return binding


def read_parent_binding(jobs,child_id):
    binding=read_receipt(jobs.directory(child_id)/'refinement_parent.json')
    parent=jobs.definition(binding['parent_id'])
    child=jobs.definition(child_id)
    root=_parent_root(jobs,parent['id'])
    if (binding['protocol']!=PROTOCOL or binding['child_id']!=child_id or child['kind']!='generation'
            or parent['config'].get('protocol')!=PROTOCOL
            or parent['definition_hash']!=binding['parent_definition_hash']
            or child['definition_hash']!=binding['child_definition_hash']
            or read_receipt(root/'challenges'/(binding['operation_key']+'.json'))!=binding):
        raise ValueError('Invalid generation parent binding')
    budget=read_receipt(root/'budget.json')
    reservation=budget['operations'][binding['operation_key']]
    if budget['deadline']!=binding['deadline'] or reservation['inputs_hash']!=binding['inputs_hash']:
        raise ValueError('Generation budget binding differs')
    return binding


def _control(path):
    return read(path).get('action') if path.exists() else None


def check_parent(jobs,binding):
    root=_parent_root(jobs,binding['parent_id'])
    budget=read_receipt(root/'budget.json')
    if time.time()>=binding['deadline'] or budget['exceeded']:
        raise BudgetExceeded('Challenge wall_time_seconds or resource budget exhausted')
    action=_control(root/'control.json')
    if action=='stop':
        raise RefinementStopped('Parent requested stop')
    return action


class BoundGenerationStore(JobStore):
    def boundary(self,identifier,event=None):
        binding=read_parent_binding(self,identifier)
        if event:
            self.event(identifier,{'type':'stage',**event})
            self.update(identifier,progress=event)
        paused=False
        while True:
            action=check_parent(self,binding)
            child_action=_control(self.directory(identifier)/'control.json')
            if action!='pause' and child_action!='pause':
                break
            if not paused:
                self.update(identifier,status='paused')
                self.event(identifier,{'type':'paused','message':'在候选执行边界暂停'})
                paused=True
            time.sleep(.1)
        if paused:
            self.update(identifier,status='running')
            self.event(identifier,{'type':'resumed'})


def recover_challenge(jobs,catalog,*,child_id,parent_id):
    binding=read_parent_binding(jobs,child_id)
    if binding['parent_id']!=parent_id:
        raise ValueError('Wrong generation parent')
    result=completed_generation_result(jobs,catalog,child_id)
    ref='challenges/'+binding['operation_key']+'-result.json'
    path=_parent_root(jobs,parent_id)/ref
    recovered=_seal({**result,'child_id':child_id,'binding_hash':binding['receipt_hash'],'receipt_ref':ref})
    if path.exists() and read_receipt(path)!=recovered:
        raise ValueError('Recovered generation result changed')
    write_json_atomic(path,recovered)
    return recovered


def run_challenge(jobs,*,parent_id,attempt_index,frozen_config,ledger):
    binding=bind_challenge(jobs,parent_id=parent_id,attempt_index=attempt_index,frozen_config=frozen_config,ledger=ledger)
    child=binding['child_id']
    directory=jobs.directory(child)
    # launch() persists starting before spawning; a queued unstarted job is the only safe launch.
    state=read(directory/'state.json')
    if state['status']=='queued' and not (directory/'generated').exists():
        check_parent(jobs,binding)
        while check_parent(jobs,binding)=='pause':
            time.sleep(.1)
        jobs.launch(child)
    try:
        while True:
            try:
                result=recover_challenge(jobs,Catalog(jobs.state_root),child_id=child,parent_id=parent_id)
            except (ValueError,OSError,KeyError,TypeError):
                state=jobs.get(child,full=False)
                if state['status'] not in {'starting','running','paused'}:
                    raise UncertainOperation('Generation has no verified terminal result')
                check_parent(jobs,binding)
                time.sleep(.1)
            else:
                ledger.settle(binding['operation_key'],actual={'new_questions':len(result['question_keys'])},
                              receipt_ref=result['receipt_ref'],outcome='complete')
                return result
    except (Exception,KeyboardInterrupt):
        ledger.settle(binding['operation_key'],actual={},receipt_ref=f'child:{child}',outcome='uncertain')
        raise


def _group_members(group):
    """Snapshot Linux descendants sharing the worker's dedicated process group."""
    if not sys.platform.startswith('linux'):
        return {}
    result={}
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            pid=int(path.name)
            try:
                stamp=process_stamp(pid)
                if stamp and os.getpgid(pid)==group:
                    result[pid]=stamp
            except OSError:
                pass
    return result


def enforce_child_deadline(jobs,child_id,deadline):
    binding=read_parent_binding(jobs,child_id)
    if deadline!=binding['deadline']:
        raise ValueError('Watchdog deadline differs from frozen budget')
    directory=jobs.directory(child_id)
    state=read(directory/'state.json')
    pid,stamp=state.get('pid'),state.get('process_stamp')
    if not pid or not stamp or process_stamp(pid)!=stamp or os.getpgid(pid)!=pid:
        return
    owner=dict(pid=pid,process_stamp=stamp,binding_hash=binding['receipt_hash'])
    write_json_atomic(directory/'refinement_watchdog_ready.json',_seal(owner))
    descendants={}
    while True:
        current=read(directory/'state.json')
        same=process_stamp(pid)==stamp
        if same:
            descendants.update(_group_members(pid))
        if current.get('pid')!=pid or current.get('process_stamp')!=stamp:
            return
        if current['status']=='complete':
            return
        if time.time()>=deadline:
            # Recheck birth identity immediately before a group signal to avoid PID reuse.
            if process_stamp(pid)==stamp and os.getpgid(pid)==pid:
                os.killpg(pid,signal.SIGKILL)
            for member,birth in descendants.items():
                if member!=pid and process_stamp(member)==birth:
                    try:
                        os.kill(member,signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            jobs.update(child_id,status='uncertain',error='Challenge deadline reached; no automatic GT replay')
            jobs.event(child_id,{'type':'deadline','message':'新题挑战达到累计截止时间'})
            return
        if not same and not any(process_stamp(p)==s for p,s in descendants.items()):
            return
        time.sleep(.1)


def start_child_watchdog(jobs,child_id):
    binding=read_parent_binding(jobs,child_id)
    check_parent(jobs,binding)
    root=Path(__file__).resolve().parents[4]
    ready=jobs.directory(child_id)/'refinement_watchdog_ready.json'
    with (jobs.directory(child_id)/'watchdog.log').open('ab') as output:
        process=subprocess.Popen([sys.executable,'-m',__name__,'--state',str(jobs.state_root),'--child',child_id,
                                  '--deadline',str(binding['deadline'])],cwd=root,
                                 env={**os.environ,'PYTHONPATH':str(root/'src')+os.pathsep+str(root)},
                                 stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    stop=min(time.time()+10,binding['deadline'])
    while time.time()<stop:
        if ready.exists():
            receipt=read_receipt(ready)
            if (receipt['binding_hash']==binding['receipt_hash'] and receipt['pid']==os.getpid()
                    and receipt['process_stamp']==process_stamp(os.getpid())):
                return
        if process.poll() is not None:
            break
        time.sleep(.05)
    raise UncertainOperation('Independent generation watchdog was not ready; GT not started')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--child',required=True)
    parser.add_argument('--deadline',type=float,required=True)
    args=parser.parse_args()
    enforce_child_deadline(JobStore(args.state),args.child,args.deadline)
