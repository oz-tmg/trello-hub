import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from spwf.config import load_config
from spwf.github import Request
from spwf.state import State
from spwf.sync import plan, synchronize
from spwf.trello import Board, Card, List, TrelloError

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


@pytest.fixture
def facts():
    data = json.loads(Path('examples/snapshot.json').read_text())
    return (Card.model_validate(data['cards'][0]), Board.model_validate(data['board']),
            [List.model_validate(item) for item in data['lists']], load_config('examples/workflow.yaml'))


def request(target=State.DOING):
    return Request('ZzYy9876', target, 'push', 'a' * 40, 'ws/ZzYy9876-demo', subject='Example')


def test_done_completes_due_with_sha_run_and_subject(facts):
    card, board, lists, config = facts
    card = card.model_copy(update={'due': '2026-10-12T00:00:00Z'})
    result = plan(request(State.DONE), card, board, lists, config, run_url='https://github.com/example/repo/actions/runs/1', now=NOW)
    assert result.target_name == 'Done — 2026-10'
    assert result.complete_due
    assert 'a' * 40 in result.comment
    assert 'Run: https://' in result.comment
    assert 'Subject: Example' in result.comment


def test_experiment_redirect_happens_before_month_resolution(facts):
    card, board, lists, config = facts
    data = card.model_dump()
    data['labels'] = [{'id': '999999999999999999999999', 'name': 'T: Experiment'}]
    config = config.model_copy(update={'done_month_format': None})
    result = plan(request(State.DONE), Card.model_validate(data), board, lists, config)
    assert result.target_name == 'Review'
    assert not result.complete_due
    assert 'experiment: human read required' in result.comment


@pytest.mark.parametrize('index,target,ci_failed', [(3, State.DONE, False), (0, State.DOING, False), (2, State.BLOCKED, True), (4, State.DONE, False)])
def test_guarded_noops_do_not_mutate_or_comment(facts, index, target, ci_failed):
    card, board, lists, config = facts
    card = card.model_copy(update={'idList': lists[index].id})
    client = Mock()
    client.get_card.return_value = card
    client.board.return_value = board
    client.lists.return_value = lists
    result = synchronize([replace(request(target), ci_failed=ci_failed)], client, config, now=NOW)
    assert result[0]['status'] == 'noop'
    client.move.assert_not_called()
    client.comment.assert_not_called()


@pytest.mark.parametrize('kind', ['duplicate', 'missing', 'archived'])
def test_missing_ambiguous_or_archived_list_prevents_move(facts, kind):
    card, board, lists, config = facts
    if kind == 'duplicate':
        lists.append(lists[0].model_copy(update={'id': '999999999999999999999999'}))
    elif kind == 'missing':
        lists.pop(0)
    else:
        lists[0] = lists[0].model_copy(update={'closed': True})
    with pytest.raises(TrelloError):
        plan(request(), card, board, lists, config)


def test_old_month_done_is_not_confused_with_this_month(facts):
    card, board, lists, config = facts
    old = List(id='999999999999999999999999', name='Done — 2026-09', closed=False)
    lists.append(old)
    card = card.model_copy(update={'idList': old.id})
    assert plan(request(State.DONE), card, board, lists, config, now=NOW).target_id == lists[4].id


def test_comment_failure_reports_partial_success(facts):
    card, board, lists, config = facts
    client = Mock()
    client.get_card.return_value = card
    client.board.return_value = board
    client.lists.return_value = lists
    client.move.return_value = True
    client.comment.side_effect = TrelloError('error')
    with pytest.raises(TrelloError, match='moved but comment failed'):
        synchronize([request()], client, config)
    assert client.move.call_count == 1
    assert client.comment.call_count == 1


def test_month_respects_vancouver_boundary_and_explicit_format(facts):
    config = facts[-1]
    instant = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    assert config.current_month(instant) == '2026-10'
    assert config.model_copy(update={'done_month_format': '%B %Y'}).current_month(instant) == 'October 2026'


def test_missing_month_format_blocks_ordinary_done(facts):
    from spwf.config import ConfigError
    card, board, lists, config = facts
    config = config.model_copy(update={'done_month_format': None})
    with pytest.raises(ConfigError, match='done_month_format'):
        plan(request(State.DONE), card, board, lists, config, now=NOW)


def test_done_cannot_alias_another_stage(facts):
    card, board, lists, config = facts
    # Even a syntactically valid config must not mark Doing as completed.
    lists[0] = lists[0].model_copy(update={'name': 'Done — 2026-10'})
    lists.pop(4)
    config = config.model_copy(update={'lists': config.lists.model_copy(update={'doing': 'Done — 2026-10'})})
    with pytest.raises(TrelloError, match='another workflow stage'):
        plan(request(State.DONE), card, board, lists, config, now=NOW)


def test_abbreviated_month_format_validates_and_resolves_board_list(facts):
    from spwf.config import WorkflowConfig
    card, board, lists, config = facts
    data = config.model_dump()
    data['done_month_format'] = '%b %Y'
    config = WorkflowConfig.model_validate(data)
    lists[-1] = lists[-1].model_copy(update={'name': 'Done — Oct 2026'})
    boundary = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    result = plan(request(State.DONE), card, board, lists, config, now=boundary)
    assert result.target_name == 'Done — Oct 2026'
