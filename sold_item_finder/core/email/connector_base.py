from __future__ import annotations

from abc import ABC, abstractmethod

from sold_item_finder.core.email.models import EmailMessage, EmailSettings


class EmailConnector(ABC):
    @abstractmethod
    def connect(self, settings: EmailSettings, secret: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def fetch_messages(self, cancel_flag: callable | None = None) -> list[EmailMessage]:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError
