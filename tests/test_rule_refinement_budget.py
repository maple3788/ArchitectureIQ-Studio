from concurrent.futures import ProcessPoolExecutor
import pytest
from architecture_iq.kb.store import canonical_hash

LIMITS = dict(max_model_calls=2, max_tokens=100, max_candidate_seed_runs=20, wall_time_seconds=60)
HASH = canonical_hash({'input': 1})


def ledger(root, clock=lambda: 10, **limits):
    from architecture_iq.studio.rule_refinement.budget import BudgetLedger
    return BudgetLedger(root, {**LIMITS, **limits}, clock=clock)


def test_rejected_and_failed_attempts_consume_limits(tmp_path):
    l = ledger(tmp_path)
    l.reserve('rev:1', {'revision_attempts': 1, 'model_calls': 1, 'tokens': 40}, inputs_hash=HASH)
    l.settle('rev:1', actual={'tokens': 8}, receipt_ref='calls/a.json', outcome='invalid')
    l.reserve('gen:1', {'generation_attempts': 1, 'new_questions': 16, 'candidate_seed_runs': 20}, inputs_hash=HASH)
    l.settle('gen:1', actual={'new_questions': 2}, receipt_ref='generation/a.json', outcome='failed')
    s = l.snapshot()
    assert s['revision_attempts'] == s['generation_attempts'] == s['model_calls'] == 1
    assert s['tokens'] == 8 and s['new_questions'] == 2 and s['candidate_seed_runs'] == 20


def _reserve_one(root, key):
    from architecture_iq.studio.rule_refinement.budget import BudgetExceeded
    try:
        ledger(root, max_model_calls=1).reserve(key, {'model_calls': 1}, inputs_hash=HASH)
        return True
    except BudgetExceeded:
        return False


def test_two_processes_cannot_reserve_same_remaining_budget(tmp_path):
    ledger(tmp_path, max_model_calls=1)
    with ProcessPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(_reserve_one, [tmp_path, tmp_path], ['a', 'b']))
    assert sorted(outcomes) == [False, True]


def test_restart_and_pause_never_reset_deadline(tmp_path):
    from architecture_iq.studio.rule_refinement.budget import BudgetExceeded
    assert ledger(tmp_path).snapshot()['deadline'] == 70
    resumed = ledger(tmp_path, clock=lambda: 70)
    assert resumed.snapshot()['deadline'] == 70
    with pytest.raises(BudgetExceeded, match='wall_time'):
        resumed.check_time()
    with pytest.raises(ValueError, match='limits'):
        ledger(tmp_path, wall_time_seconds=100)


def test_uncertain_reservation_is_not_refundable_or_retryable(tmp_path):
    from architecture_iq.studio.rule_refinement.budget import UncertainOperation
    l = ledger(tmp_path)
    original = l.reserve('a', {'model_calls': 1, 'tokens': 40}, inputs_hash=HASH)
    assert l.reserve('a', {'model_calls': 1, 'tokens': 40}, inputs_hash=HASH) == original
    l.settle('a', actual={'tokens': 0}, receipt_ref='calls/a.json', outcome='uncertain')
    assert l.snapshot()['tokens'] == 40
    with pytest.raises(UncertainOperation):
        l.reserve('a', {'model_calls': 1, 'tokens': 40}, inputs_hash=HASH)
    with pytest.raises(UncertainOperation):
        l.settle('a', actual={'tokens': 0}, receipt_ref='calls/a.json', outcome='complete')


def test_exact_limit_missing_usage_and_idempotent_settlement(tmp_path):
    from architecture_iq.studio.rule_refinement.budget import BudgetExceeded
    l = ledger(tmp_path)
    l.reserve('a', {'model_calls': 2, 'tokens': 100}, inputs_hash=HASH)
    first = l.settle('a', actual={}, receipt_ref='calls/a.json', outcome='complete')
    assert l.settle('a', actual={}, receipt_ref='calls/a.json', outcome='complete') == first
    assert l.snapshot()['tokens'] == 100 and l.snapshot()['model_calls'] == 2
    with pytest.raises(BudgetExceeded):
        l.reserve('b', {'model_calls': 1}, inputs_hash=HASH)


def test_actual_over_reservation_is_persisted_and_blocks_more_work(tmp_path):
    from architecture_iq.studio.rule_refinement.budget import BudgetExceeded
    l = ledger(tmp_path)
    l.reserve('a', {'model_calls': 1, 'tokens': 40}, inputs_hash=HASH)
    with pytest.raises(BudgetExceeded, match='reservation'):
        l.settle('a', actual={'tokens': 41}, receipt_ref='calls/a.json', outcome='complete')
    assert l.snapshot()['tokens'] == 41
    with pytest.raises(BudgetExceeded):
        l.reserve('b', {'model_calls': 1}, inputs_hash=HASH)


@pytest.mark.parametrize('cost', [{}, {'tokens': 0}, {'tokens': -1}, {'tokens': float('nan')}, {'tokens': True}, {'unknown': 1}])
def test_invalid_cost(tmp_path, cost):
    with pytest.raises(ValueError):
        ledger(tmp_path).reserve('a', cost, inputs_hash=HASH)


@pytest.mark.parametrize('value', [0, -1, float('nan'), True])
def test_invalid_limits(tmp_path, value):
    with pytest.raises(ValueError):
        ledger(tmp_path, max_tokens=value)


def test_identity_and_settlement_cannot_change(tmp_path):
    l = ledger(tmp_path)
    l.reserve('a', {'model_calls': 1, 'revision_attempts': 1}, inputs_hash=HASH)
    with pytest.raises(ValueError):
        l.reserve('a', {'model_calls': 1, 'revision_attempts': 1}, inputs_hash=canonical_hash('changed'))
    l.settle('a', actual={'model_calls': 0, 'revision_attempts': 0}, receipt_ref='calls/a.json', outcome='failed')
    assert l.snapshot()['model_calls'] == l.snapshot()['revision_attempts'] == 1
    with pytest.raises(ValueError):
        l.settle('a', actual={}, receipt_ref='calls/b.json', outcome='complete')
