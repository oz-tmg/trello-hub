"""Small Trello REST client. HTTP failures never expose URLs or response bodies."""

import re
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, ValidationError


class TrelloError(RuntimeError):
    """Safe-to-log integration error."""


class Record(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)


class Board(Record):
    id: str
    closed: bool


class List(Record):
    id: str
    name: str
    closed: bool


class Label(Record):
    id: str
    name: str


class Card(Record):
    id: str
    shortLink: str
    idBoard: str
    idList: str
    closed: bool
    labels: list[Label]
    due: str | None
    dueComplete: bool


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]{8}|[a-f0-9]{24}", value):
        raise TrelloError("Invalid Trello identifier")
    return value


class TrelloClient:
    def __init__(self, board: str, key: str, token: str, *, session=None):
        if not key or not token:
            raise TrelloError("TRELLO_KEY and TRELLO_TOKEN are required")
        self.board_ref = identifier(board)
        self._auth = {"key": key, "token": token}
        self._session = session or requests.Session()
        self._board: Board | None = None
        self._lists: list[List] | None = None

    def _request(self, method: str, path: str, **params) -> Any:
        try:
            response = self._session.request(
                method, "https://api.trello.com/1/" + path,
                params=self._auth if method != "GET" else {**self._auth, **params},
                json=params if method != "GET" else None,
                headers={"Accept": "application/json"}, timeout=(5, 20),
                allow_redirects=False,
            )
            if not 200 <= response.status_code < 300:
                raise TrelloError(f"Trello request failed (HTTP {response.status_code})")
            return response.json()
        except (requests.RequestException, ValueError):
            raise TrelloError("Trello request failed: transport or invalid JSON") from None

    def board(self) -> Board:
        if self._board is None:
            try:
                self._board = Board.model_validate(self._request(
                    "GET", f"boards/{self.board_ref}", fields="id,closed"
                ))
            except ValidationError:
                raise TrelloError("Invalid Trello board response") from None
        if self._board.closed:
            raise TrelloError("Configured board is archived")
        return self._board

    def lists(self) -> list[List]:
        if self._lists is None:
            data = self._request("GET", f"boards/{identifier(self.board().id)}/lists", filter="open")
            try:
                if not isinstance(data, list):
                    raise ValueError
                self._lists = [List.model_validate(item) for item in data]
            except (ValueError, TypeError):
                raise TrelloError("Invalid Trello list response") from None
        return self._lists

    def get_card(self, shortlink: str) -> Card:
        data = self._request("GET", f"cards/{identifier(shortlink)}",
                             fields="id,shortLink,idBoard,idList,closed,labels,due,dueComplete")
        try:
            card = Card.model_validate(data)
        except ValidationError:
            raise TrelloError("Invalid Trello card response") from None
        if card.idBoard != self.board().id:
            raise TrelloError("Card does not belong to the configured board")
        if card.closed:
            raise TrelloError("Card is archived")
        return card

    def move(self, card: Card, target_id: str, *, complete_due: bool = False) -> bool:
        # Refetch before mutation: reject changes to list, labels, dates or archive state.
        current = self.get_card(card.shortLink)
        if current != card:
            raise TrelloError("Card changed during planning; rerun with fresh state")
        if not any(item.id == target_id and not item.closed for item in self.lists()):
            raise TrelloError("Target is not an open list on the configured board")
        if current.idList == target_id:
            return False
        params: dict[str, Any] = {"idList": identifier(target_id)}
        if complete_due and current.due:
            params["dueComplete"] = True
        self._request("PUT", f"cards/{identifier(current.id)}", **params)
        return True

    def comment(self, shortlink: str, text: str) -> None:
        card = self.get_card(shortlink)
        self._request("POST", f"cards/{identifier(card.id)}/actions/comments", text=text)

    def set_due(self, shortlink: str, due: str | None) -> None:
        card = self.get_card(shortlink)
        if card.due != due:
            self._request("PUT", f"cards/{identifier(card.id)}", due=due)

    def attach_label(self, shortlink: str, label_id: str) -> None:
        label_id = identifier(label_id)
        card = self.get_card(shortlink)
        if label_id not in {label.id for label in card.labels}:
            self._request("POST", f"cards/{identifier(card.id)}/idLabels", value=label_id)
