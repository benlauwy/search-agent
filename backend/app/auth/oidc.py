"""Generic OIDC auth provider. Google is just a configuration of this class."""

from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.jwk import KeySet

from .base import Identity


class OIDCProvider:
    def __init__(
        self,
        name: str,
        issuer: str,
        client_id: str,
        client_secret: str,
        scopes: str = "openid email profile",
    ):
        self.name = name
        self.issuer = issuer
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
        self._metadata: dict | None = None
        self._jwks: dict | None = None

    async def _discover(self) -> dict:
        if self._metadata is None:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"
                )
                resp.raise_for_status()
                self._metadata = resp.json()
        return self._metadata

    async def _get_jwks(self) -> dict:
        if self._jwks is None:
            meta = await self._discover()
            async with httpx.AsyncClient() as client:
                resp = await client.get(meta["jwks_uri"])
                resp.raise_for_status()
                self._jwks = resp.json()
        return self._jwks

    async def authorize_url_async(self, redirect_uri: str, state: str) -> str:
        meta = await self._discover()
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.scopes,
            "state": state,
        }
        return f"{meta['authorization_endpoint']}?{urlencode(params)}"

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        # Sync wrapper used only when metadata is already cached; routes use the async variant.
        raise NotImplementedError("use authorize_url_async")

    async def exchange_code(self, code: str, redirect_uri: str) -> Identity:
        meta = await self._discover()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                meta["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            resp.raise_for_status()
            tokens = resp.json()
        key_set = KeySet.import_key_set(await self._get_jwks())
        token = jwt.decode(tokens["id_token"], key_set)
        registry = jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": self.issuer},
            aud={"essential": True, "value": self.client_id},
            exp={"essential": True},
        )
        registry.validate(token.claims)
        claims = token.claims
        return Identity(
            provider=self.name,
            subject=str(claims["sub"]),
            email=claims.get("email", ""),
            name=claims.get("name", ""),
            picture=claims.get("picture", ""),
        )


def google_provider(client_id: str, client_secret: str) -> OIDCProvider:
    return OIDCProvider(
        name="google",
        issuer="https://accounts.google.com",
        client_id=client_id,
        client_secret=client_secret,
    )
