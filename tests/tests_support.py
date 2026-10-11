from unittest.mock import Mock


def queued_session(*data):
    responses = []
    for item in data:
        response = Mock(status_code=200)
        response.json.return_value = item
        responses.append(response)
    session = Mock()
    session.request.side_effect = responses
    return session
