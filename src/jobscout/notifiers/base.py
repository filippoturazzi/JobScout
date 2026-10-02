"""The channel contract. Implementations depend only on `models` and `config`."""

from typing import Protocol


class Notifier(Protocol):
    """Somewhere a finished message can be delivered.

    Deliberately narrow: it takes rendered text, not a list of matches, so a channel
    never has to know what a `Match` is or how a digest is composed.
    """

    def send(self, subject: str, body: str) -> None: ...
