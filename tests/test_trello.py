import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from spwf.trello import TrelloClient, TrelloError

@pytest.fixture
def snapshot():
    return json.loads(Path('examples/snapshot.json').read_text())


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    return result


def make_client(*responses):
    session = Mock()
    session.request.side_effect = responses
    return TrelloClient('AbCd1234', 'secret-key', 'secret-token', session=session), session


def test_board_and_list_resolution_is_cached(snapshot):
    client, session = make_client(response(snapshot['board']), response(snapshot['lists']))
    assert client.lists() == client.lists()
    assert client.board().id == snapshot['board']['id']
    assert session.request.call_count == 2
    for call in session.request.call_args_list:
        assert call.kwargs['timeout'] == (5, 20)
        assert call.kwargs['allow_redirects'] is False


@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
def test_http_failures_are_safe_and_never_retried(status):
    client, session = make_client(response({'error': 'secret-token'}, status))
    with pytest.raises(TrelloError) as error:
        client.board()
    assert 'secret' not in str(error.value)
    assert session.request.call_count == 1


@pytest.mark.parametrize('failure', [requests.Timeout('secret-token'), requests.ConnectionError('secret-key')])
def test_transport_failures_do_not_leak_credentials(failure):
    client, _ = make_client(failure)
    with pytest.raises(TrelloError) as error:
        client.board()
    assert 'secret' not in str(error.value)
    assert error.value.__suppress_context__


def test_invalid_json_and_schema_are_safe():
    bad_json = response(None)
    bad_json.json.side_effect = ValueError('secret-token')
    for bad in [bad_json, response({'secret': 'secret-token'})]:
        client, _ = make_client(bad)
        with pytest.raises(TrelloError) as error:
            client.board()
        assert 'secret' not in str(error.value)


@pytest.mark.parametrize('change', [{'idBoard': '999999999999999999999999'}, {'closed': True}])
def test_foreign_or_archived_card_cannot_be_read_for_mutation(snapshot, change):
    card = {**snapshot['cards'][0], **change}
    client, session = make_client(response(card), response(snapshot['board']))
    with pytest.raises(TrelloError):
        client.get_card('ZzYy9876')
    assert all(call.args[0] == 'GET' for call in session.request.call_args_list)


def test_move_and_due_completion_share_one_put(snapshot):
    card = {**snapshot['cards'][0], 'due': '2026-10-12T00:00:00Z'}
    client, session = make_client(response(card), response(snapshot['board']), response(card),
                                  response(snapshot['lists']), response({}))
    initial = client.get_card('ZzYy9876')
    assert client.move(initial, snapshot['lists'][0]['id'], complete_due=True)
    call = session.request.call_args
    assert call.args[0] == 'PUT'
    assert call.kwargs['json'] == {'idList': snapshot['lists'][0]['id'], 'dueComplete': True}


def test_already_in_list_is_no_write(snapshot):
    card = {**snapshot['cards'][0], 'idList': snapshot['lists'][0]['id']}
    client, session = make_client(response(card), response(snapshot['board']), response(card), response(snapshot['lists']))
    initial = client.get_card('ZzYy9876')
    assert not client.move(initial, card['idList'], complete_due=True)
    assert all(call.args[0] == 'GET' for call in session.request.call_args_list)


def test_card_changed_between_plan_and_write_is_rejected(snapshot):
    card = snapshot['cards'][0]
    changed = {**card, 'labels': [{'id': '999999999999999999999999', 'name': 'T: Experiment'}]}
    client, session = make_client(response(card), response(snapshot['board']), response(changed))
    initial = client.get_card('ZzYy9876')
    with pytest.raises(TrelloError, match='changed'):
        client.move(initial, snapshot['lists'][0]['id'])
    assert all(call.args[0] == 'GET' for call in session.request.call_args_list)


def test_target_outside_board_is_rejected(snapshot):
    card = snapshot['cards'][0]
    client, session = make_client(response(card), response(snapshot['board']), response(card), response(snapshot['lists']))
    initial = client.get_card('ZzYy9876')
    with pytest.raises(TrelloError, match='Target'):
        client.move(initial, '999999999999999999999999')
    assert all(call.args[0] == 'GET' for call in session.request.call_args_list)


def test_comment_due_and_label_endpoints(snapshot):
    card = snapshot['cards'][0]
    client, session = make_client(response(card), response(snapshot['board']), response({}),
                                  response(card), response({}), response(card), response({}))
    client.comment('ZzYy9876', 'SHA: demo')
    client.set_due('ZzYy9876', '2026-10-12T00:00:00Z')
    client.attach_label('ZzYy9876', '999999999999999999999999')
    mutations = [call for call in session.request.call_args_list if call.args[0] != 'GET']
    assert mutations[0].args[1].endswith('/actions/comments')
    assert mutations[0].kwargs['json'] == {'text': 'SHA: demo'}
    assert mutations[1].kwargs['json'] == {'due': '2026-10-12T00:00:00Z'}
    assert mutations[2].args[1].endswith('/idLabels')


def test_existing_due_and_label_do_not_write(snapshot):
    card = copy.deepcopy(snapshot['cards'][0])
    card['labels'] = [{'id': '999999999999999999999999', 'name': 'Infra'}]
    client, session = make_client(response(card), response(snapshot['board']), response(card))
    client.set_due('ZzYy9876', None)
    client.attach_label('ZzYy9876', card['labels'][0]['id'])
    assert all(call.args[0] == 'GET' for call in session.request.call_args_list)
