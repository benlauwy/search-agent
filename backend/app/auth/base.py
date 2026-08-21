from dataclasses import dataclass
from typing import Protocol


@dataclass
class Identity:
    provider: str
    subject: str
    email: str
    name: str = ""
    picture: str = ""


class AuthProvider(Protocol):
    """Pluggable authentication provider.

    Implementations produce an authorize URL to redirect the browser to,
    and exchange the callback code for a verified Identity.
    """

    name: str

    def authorize_url(self, redirect_uri: str, state: str) -> str: ...

    async def exchange_code(self, code: str, redirect_uri: str) -> Identity: ...
