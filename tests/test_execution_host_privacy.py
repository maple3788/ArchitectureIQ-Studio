"""Private execution configuration gates inference without publishing host details."""

import importlib

import pytest
from fastapi.testclient import TestClient

from architecture_iq.kb import cli, experiments
from services.kb_workflow_api.app import create_app


@pytest.mark.parametrize(
    'system,declared,authorized,allowed',
    [
        ('Linux', 'execution.example.test', 'execution.example.test', True),
        ('Linux', '', '', False),
        ('Linux', 'execution.example.test', '', False),
        ('Linux', '', 'execution.example.test', False),
        ('Linux', 'other.example.test', 'execution.example.test', False),
        ('Darwin', 'execution.example.test', 'execution.example.test', False),
    ],
)
def test_cli_and_gt_use_the_same_private_host_gate(
    monkeypatch, system, declared, authorized, allowed,
):
    monkeypatch.setattr(cli.platform, 'system', lambda: system)
    monkeypatch.setenv('ARCHITECTURE_IQ_KB_EXECUTION_HOST', declared)
    monkeypatch.setenv('ARCHITECTURE_IQ_KB_AUTHORIZED_HOST', authorized)
    if allowed:
        cli.require_execution_host(True)
        experiments._require_execution_host()
    else:
        with pytest.raises(ValueError) as cli_error:
            cli.require_execution_host(True)
        with pytest.raises(RuntimeError) as gt_error:
            experiments._require_execution_host()
        for host in (declared, authorized):
            if host:
                assert host not in str(cli_error.value)
                assert host not in str(gt_error.value)
    with pytest.raises(ValueError, match='execute'):
        cli.require_execution_host(False)


@pytest.mark.parametrize('configured', [False, True])
def test_api_host_status_uses_private_configuration_without_disclosing_it(
    monkeypatch, tmp_path, configured,
):
    # Import native dependencies on the actual platform before mocking the gate.
    importlib.import_module('architecture_iq.studio.generation')
    monkeypatch.setattr(cli.platform, 'system', lambda: 'Linux')
    host = 'private-execution.example.test'
    monkeypatch.setenv('ARCHITECTURE_IQ_KB_EXECUTION_HOST', host)
    monkeypatch.setenv('ARCHITECTURE_IQ_KB_AUTHORIZED_HOST', host if configured else '')
    client = TestClient(create_app(state_root=tmp_path, allowed_roots=[tmp_path]))
    response = client.get('/api/studio/bootstrap')
    assert response.status_code == 200
    assert response.json()['service']['execution_enabled'] is configured
    assert response.json()['service']['host'] == (
        'authorized execution host' if configured else 'local editor'
    )
    assert host not in response.text
