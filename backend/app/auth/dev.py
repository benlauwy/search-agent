"""Dev auth provider: instant login as a fixed local user. Never enable in production."""

from .base import Identity


class DevProvider:
    name = "dev"

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        return f"{redirect_uri}?code=dev&state={state}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Identity:
        return Identity(
            provider="dev",
            subject="dev-user",
            email="dev@localhost",
            name="Dev User",
        )
