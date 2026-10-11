"""Durable cumulative reservations, with a fixed wall-clock deadline."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time

from architecture_iq.kb.roles import exclusive_lock, _seal, read_receipt
from architecture_iq.kb.store import write_json_atomic
from .contracts import digest, fields, text, validate_limits

COUNTERS = {name: 'max_' + name for name in (
    'model_calls', 'tokens', 'candidate_seed_runs', 'new_questions',
    'revision_attempts', 'generation_attempts',
)}
NONREFUNDABLE = {'model_calls', 'revision_attempts', 'generation_attempts'}
OUTCOMES = {'complete', 'invalid', 'rejected', 'failed', 'uncertain'}


class BudgetExceeded(RuntimeError):
    pass


class UncertainOperation(RuntimeError):
    pass


def _cost(value, *, reservation=False):
    fields(value, COUNTERS)
    if any(type(v) is not int or v < 0 for v in value.values()) or reservation and not any(value.values()):
        raise ValueError('Costs must be nonnegative integer counters with a positive reservation')
    return deepcopy(value)


class BudgetLedger:
    def __init__(self, root: Path, limits: dict, *, clock=time.time):
        self.root, self.clock = Path(root), clock
        self.path, self.lock = self.root / 'budget.json', self.root / 'budget.lock'
        self.limits = validate_limits(limits)
        with exclusive_lock(self.lock):
            if self.path.exists():
                if self._read()['limits'] != self.limits:
                    raise ValueError('Frozen limits changed')
            else:
                started = self.clock()
                self._write(dict(limits=self.limits, started_at=started,
                                 deadline=started + self.limits['wall_time_seconds'], operations={}, exceeded=None))

    def _read(self):
        return read_receipt(self.path)

    def _write(self, data):
        write_json_atomic(self.path, _seal(data))

    def _check(self, data):
        if data['exceeded']:
            raise BudgetExceeded(data['exceeded'])
        if self.clock() >= data['deadline']:
            raise BudgetExceeded('wall_time_seconds exhausted')

    @staticmethod
    def _totals(data):
        return {name: sum(op['charged'].get(name, 0) for op in data['operations'].values()) for name in COUNTERS}

    def snapshot(self):
        with exclusive_lock(self.lock):
            data = self._read()
            return {**deepcopy(data), **self._totals(data), 'remaining_seconds': max(0, data['deadline'] - self.clock())}

    def check_time(self):
        with exclusive_lock(self.lock):
            self._check(self._read())

    def reserve(self, operation_key: str, cost: dict, *, inputs_hash: str):
        text(operation_key, maximum=300)
        digest(inputs_hash)
        cost = _cost(cost, reservation=True)
        with exclusive_lock(self.lock):
            data = self._read()
            old = data['operations'].get(operation_key)
            if old:
                if old['inputs_hash'] != inputs_hash or old['reserved'] != cost:
                    raise ValueError('Operation inputs or reservation changed')
                if old['outcome'] == 'uncertain':
                    raise UncertainOperation(operation_key)
                return deepcopy(old)
            self._check(data)
            totals = self._totals(data)
            for name, amount in cost.items():
                if totals[name] + amount > self.limits[COUNTERS[name]]:
                    raise BudgetExceeded(f'{COUNTERS[name]} exhausted')
            op = dict(operation_key=operation_key, inputs_hash=inputs_hash, reserved=cost,
                      charged=deepcopy(cost), outcome='pending', receipt_ref=None)
            data['operations'][operation_key] = op
            self._write(data)
            return deepcopy(op)

    def settle(self, operation_key: str, *, actual: dict, receipt_ref: str, outcome: str):
        actual = _cost(actual)
        text(receipt_ref, maximum=1000)
        if outcome not in OUTCOMES:
            raise ValueError('Invalid operation outcome')
        with exclusive_lock(self.lock):
            data = self._read()
            op = data['operations'].get(operation_key)
            if op is None:
                raise ValueError('Operation was not reserved')
            settlement = dict(actual=actual, receipt_ref=receipt_ref, outcome=outcome)
            if op['outcome'] != 'pending':
                if op.get('settlement') == settlement:
                    return deepcopy(op)
                if op['outcome'] == 'uncertain':
                    raise UncertainOperation(operation_key)
                raise ValueError('Settled operation is immutable')
            if set(actual) - set(op['reserved']):
                raise ValueError('Actual usage includes unreserved counters')
            charged = {k: actual.get(k, v) for k, v in op['reserved'].items()}
            for k, v in op['reserved'].items():
                if k in NONREFUNDABLE or outcome == 'uncertain':
                    charged[k] = max(charged[k], v)
            exceeded = any(charged[k] > op['reserved'][k] for k in charged)
            op.update(charged=charged, settlement=settlement, receipt_ref=receipt_ref, outcome=outcome)
            if exceeded:
                data['exceeded'] = 'Actual usage exceeded reservation'
            self._write(data)
            if exceeded:
                raise BudgetExceeded(data['exceeded'])
            return deepcopy(op)
