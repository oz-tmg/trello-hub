import json
from unittest.mock import Mock

import pytest

from spwf.cli import main


BASE = ['sync', '--config', 'examples/workflow.yaml', '--event-name', 'push', '--event-path', 'examples/push.json']


def records(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_offline_preview_uses_guards_and_never_constructs_clients(monkeypatch, capsys):
    from spwf import cli
    github = Mock(side_effect=AssertionError('Must stay offline'))
    trello = Mock(side_effect=AssertionError('Must stay offline'))
    monkeypatch.setattr(cli, 'GitHubClient', github)
    monkeypatch.setattr(cli, 'TrelloClient', trello)
    assert main([*BASE, '--snapshot', 'examples/snapshot.json']) == 0
    output = records(capsys)
    assert output[0]['target_name'] == 'Doing'
    assert output[-1]['network_calls'] == 0
    github.assert_not_called()
    trello.assert_not_called()


def test_no_snapshot_is_explicitly_unverified(capsys):
    assert main(BASE) == 0
    output = records(capsys)
    assert output[0]['status'] == 'unverified'
    assert 'target_id' not in output[0]


def test_live_rejects_fixture_state(capsys):
    assert main([*BASE, '--live', '--snapshot', 'examples/snapshot.json']) == 1
    assert records(capsys)[0]['status'] == 'error'


def test_soft_failure_returns_success_but_logs_error(monkeypatch, capsys):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    assert main([*BASE, '--live', '--repository', 'example/consumer', '--soft-fail']) == 0
    assert records(capsys)[0]['status'] == 'error'


def test_errors_and_event_text_redact_known_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TRELLO_TOKEN', 'dangerous-token')
    payload = json.loads(open('examples/push.json').read())
    payload['head_commit']['message'] = 'dangerous-token'
    path = tmp_path / 'event.json'
    path.write_text(json.dumps(payload))
    assert main([*BASE, '--event-path', str(path), '--snapshot', 'examples/snapshot.json']) == 0
    text = capsys.readouterr().out
    assert 'dangerous-token' not in text
    assert '[redacted]' in text


def test_smoke_is_read_only(monkeypatch, capsys):
    from spwf import cli
    from spwf.trello import List
    snapshot = json.loads(open('examples/snapshot.json').read())
    # Use a real current-month list rather than fixing the clock for this check.
    from spwf.config import load_config
    config = load_config('examples/workflow.yaml')
    snapshot['lists'][-1]['name'] = config.lists.done_prefix + config.current_month()
    client = Mock()
    client.lists.return_value = [List.model_validate(item) for item in snapshot['lists']]
    monkeypatch.setattr(cli, 'TrelloClient', Mock(return_value=client))
    assert main(['smoke', '--config', 'examples/workflow.yaml', '--card', 'ZzYy9876']) == 0
    assert records(capsys)[0]['writes'] == 0
    assert {call[0] for call in client.mock_calls} == {'board', 'lists', 'get_card'}


def test_live_cli_moves_and_comments_using_current_github_context(monkeypatch, capsys):
    from spwf import cli
    from spwf.github import parse_event
    from spwf.config import load_config
    from spwf.trello import TrelloClient
    from tests_support import queued_session

    data = json.loads(open('examples/snapshot.json').read())
    card = data['cards'][0]
    moved = {**card, 'idList': data['lists'][0]['id']}
    session = queued_session(card, data['board'], data['lists'], card, {}, moved, {})
    real_client = TrelloClient('AbCd1234', 'key', 'token', session=session)
    monkeypatch.setattr(cli, 'TrelloClient', Mock(return_value=real_client))
    github = Mock()
    github.resolve.return_value = parse_event('push', json.loads(open('examples/push.json').read()), load_config('examples/workflow.yaml'))
    monkeypatch.setattr(cli, 'GitHubClient', Mock(return_value=github))
    assert main([*BASE, '--live', '--repository', 'example/consumer', '--run-url', 'https://github.com/example/consumer/actions/runs/1']) == 0
    output = records(capsys)
    assert output[0]['status'] == 'moved'
    mutations = [call for call in session.request.call_args_list if call.args[0] != 'GET']
    assert [call.args[0] for call in mutations] == ['PUT', 'POST']
    assert 'Run: https://' in mutations[1].kwargs['json']['text']
