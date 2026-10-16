"""The experiment runner must work from this checkout, with no real calls locally."""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))


def test_bundled_entrypoint_help_is_independent_of_other_checkouts(tmp_path):
    runner=ROOT/'tools/kb_loop/loop.py'
    assert runner.is_file(), 'KB loop runner must be owned by Studio'
    result=subprocess.run([sys.executable,str(runner),'--help'],cwd=tmp_path,
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'run-forever' in result.stdout


def test_pairwise_rule_honors_parameter_ratio():
    from kb_claim_pairwise_eval import predicted_winner
    rule={'max_param_ratio':2,'predict':{'higher_better':'lr'}}
    a={'lr':.001,'params':100}; b={'lr':.0001,'params':300}
    assert predicted_winner(rule,a,b) is None
    b['params']=150
    assert predicted_winner(rule,a,b)==0


def test_real_migrated_source_can_prepare_a_complete_runtime(tmp_path):
    from tools.kb_consistency_runtime import prepare_runtime
    destination=tmp_path/'runtime'
    manifest=prepare_runtime(ROOT,destination)
    assert 'tools/kb_loop/loop.py' in manifest['installed_hashes']
    result=subprocess.run([sys.executable,str(destination/'tools/kb_loop/loop.py'),'--help'],cwd=tmp_path,
        env={**os.environ,'PYTHONPATH':str(destination/'src')},capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_imported_dataset_fields_match_frozen_rule_dsl():
    from kb_claim_pairwise_eval import dataset_view
    regression = dataset_view({"family": "multivariate_regression", "selection_metric": "test_mse",
                               "params": {"input_dim": 5, "expression": "x0 + x0*x2"}})
    assert regression["n_used_inputs"] == 2
    language = dataset_view({"family": "bigram_lm", "selection_metric": "test_ce",
                             "params": {"alpha": 0.5}})
    assert language["transition_alpha"] == 0.5
    assert regression["transition_alpha"] is None


def test_lineage_evidence_counts_datasets_not_repeated_pairs():
    from kb_claim_pairwise_eval import lineage_stats
    rows = [{"dataset_id": "same-data", "decisive": True, "correct": True}] * 100
    rows += [{"dataset_id": "other-data", "decisive": True, "correct": False}]
    rows += [{"dataset_id": "uncertain-data", "decisive": False, "correct": False}]
    stats = lineage_stats(rows, alpha=0.01)
    assert stats["lineages_determined"] == 2
    assert stats["lineage_success_rate"] == 0.5
    assert stats["lineages_no_decisive"] == 1
    assert stats["lineage_strict_rate"] == 1 / 3
    assert stats["lineage_hoeffding_lb"] < lineage_stats(rows, alpha=0.05)["lineage_hoeffding_lb"]


def test_example_api_roots_make_one_chat_endpoint(tmp_path):
    import yaml
    from kb_loop.qwen import ReplicaPool

    config = yaml.safe_load((ROOT / "configs/kb_loop/loop.example.yaml").read_text())
    for name in ("qwen", "proposer"):
        calls = []
        def mock_transport(url, payload, timeout):
            calls.append(url)
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}
        pool = ReplicaPool(config[name]["base_urls"], "mock", tmp_path / name, transport=mock_transport)
        pool.complete([{"role": "user", "content": "test"}])
        assert calls == ["https://api.example.invalid/v1/chat/completions"]
