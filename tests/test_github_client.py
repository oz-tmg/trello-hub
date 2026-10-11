from unittest.mock import Mock

import pytest
import requests

from spwf.github_client import GitHubClient, GitHubError
from spwf.state import State


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = data
    return result


def pull(state='open', merged=False):
    return {
        'number': 1, 'state': state, 'merged': merged,
        'base': {'ref': 'main', 'repo': {'full_name': 'example/consumer'}},
        'head': {'ref': 'ws/AbCd1234-demo', 'sha': 'a' * 40, 'repo': {'full_name': 'example/consumer'}},
        'body': None, 'merge_commit_sha': 'b' * 40,
        'html_url': 'https://github.com/example/consumer/pull/1',
    }


def push(sha='a' * 40):
    return {'repository': {'full_name': 'example/consumer'},
            'ref': 'refs/heads/ws/AbCd1234-demo', 'created': True,
            'after': sha, 'commits': [], 'head_commit': None}


def client(*data):
    session = Mock()
    session.get.side_effect = [response(item) for item in data]
    return GitHubClient('example/consumer', 'github-secret', session=session), session


@pytest.mark.parametrize('state,merged,target', [('open', False, State.REVIEW), ('closed', True, State.DONE)])
def test_delayed_push_converges_to_current_pr_state(config, state, merged, target):
    github, session = client([{'number': 1}], pull(state, merged))
    result = github.resolve('push', push(), config)
    assert result[0].target == target
    assert result[0].source == 'pull_request'
    assert session.get.call_count == 2


def test_delayed_open_event_after_merge_uses_merge_sha(config):
    github, _ = client(pull('closed', True))
    payload = {'repository': {'full_name': 'example/consumer'}, 'number': 1, 'action': 'opened'}
    result = github.resolve('pull_request', payload, config)
    assert result[0].target == State.DONE
    assert result[0].sha == 'b' * 40


def test_closed_unmerged_pr_suppresses_delayed_push(config):
    github, _ = client([{'number': 1}], pull('closed'))
    assert github.resolve('push', push(), config) == []


def test_unrelated_pr_does_not_override_card(config):
    pr = pull()
    pr['head']['ref'] = 'ws/ZzYy9876-other'
    github, _ = client([{'number': 1}], pr)
    assert github.resolve('push', push(), config)[0].target == State.DOING


def test_no_pr_leaves_push_intent(config):
    github, _ = client([])
    assert github.resolve('push', push(), config)[0].target == State.DOING


def test_lookup_failure_fails_closed(config):
    session = Mock()
    session.get.side_effect = requests.Timeout('github-secret')
    github = GitHubClient('example/consumer', 'github-secret', session=session)
    with pytest.raises(GitHubError) as error:
        github.resolve('push', push(), config)
    assert 'github-secret' not in str(error.value)


def test_failed_permissions_never_echo_response(config):
    session = Mock()
    session.get.return_value = response({'secret': 'github-secret'}, 403)
    github = GitHubClient('example/consumer', 'github-secret', session=session)
    with pytest.raises(GitHubError, match='HTTP 403'):
        github.resolve('push', push(), config)


def test_stale_ci_result_is_ignored(config):
    github, _ = client({'sha': 'b' * 40})
    payload = {'repository': {'full_name': 'example/consumer'}, 'action': 'completed',
               'workflow_run': {'conclusion': 'failure', 'head_branch': 'ws/AbCd1234-demo',
                                'head_sha': 'a' * 40, 'html_url': 'https://github.com/example/consumer/actions/runs/1'}}
    assert github.resolve('workflow_run', payload, config) == []


def test_repository_mismatch_rejected(config):
    github, session = client()
    payload = push()
    payload['repository']['full_name'] = 'other/project'
    with pytest.raises(GitHubError, match='another repository'):
        github.resolve('push', payload, config)
    session.get.assert_not_called()


def test_pagination_is_explicit_and_bounded():
    github, session = client([{'number': 1}] * 100, [{'number': 2}])
    assert len(github.associated('a' * 40)) == 101
    assert session.get.call_args.kwargs['params']['page'] == 2


def test_conflicting_associated_prs_are_rejected(config):
    github, _ = client([{'number': 1}, {'number': 2}], pull(), pull('closed', True))
    with pytest.raises(GitHubError, match='Conflicting'):
        github.resolve('push', push(), config)


def test_fork_pr_cannot_override_trusted_push(config):
    pr = pull()
    pr['head']['repo']['full_name'] = 'someone/fork'
    github, _ = client([{'number': 1}], pr)
    assert github.resolve('push', push(), config)[0].target == State.DOING


def test_direct_fork_pr_is_skipped(config):
    pr = pull()
    pr['head']['repo']['full_name'] = 'someone/fork'
    github, _ = client(pr)
    payload = {'repository': {'full_name': 'example/consumer'}, 'number': 1, 'action': 'opened'}
    assert github.resolve('pull_request', payload, config) == []
