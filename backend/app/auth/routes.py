import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import User
from .base import Identity
from .dev import DevProvider
from .oidc import OIDCProvider, google_provider

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "sa_session"
STATE_COOKIE = "sa_oauth_state"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="session")


def get_auth_provider():
    s = get_settings()
    if s.auth_provider == "google":
        if not s.google_client_id or not s.google_client_secret:
            raise HTTPException(500, "Google auth not configured")
        return google_provider(s.google_client_id, s.google_client_secret)
    return DevProvider()


def _redirect_uri() -> str:
    return f"{get_settings().api_url}/api/auth/callback"


async def _upsert_user(db: AsyncSession, identity: Identity) -> User:
    s = get_settings()
    if s.allowed_email_domains:
        domains = {d.strip().lower() for d in s.allowed_email_domains.split(",") if d.strip()}
        domain = identity.email.rsplit("@", 1)[-1].lower() if "@" in identity.email else ""
        if domain not in domains:
            raise HTTPException(403, "Email domain not allowed")
    result = await db.execute(
        select(User).where(User.provider == identity.provider, User.subject == identity.subject)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            provider=identity.provider,
            subject=identity.subject,
            email=identity.email,
            name=identity.name,
            picture=identity.picture,
        )
        db.add(user)
    else:
        user.email = identity.email
        user.name = identity.name
        user.picture = identity.picture
    await db.commit()
    await db.refresh(user)
    return user


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = _serializer().dumps({"uid": user_id})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature as e:
        raise HTTPException(401, "Invalid session") from e
    user = await db.get(User, data["uid"])
    if user is None:
        raise HTTPException(401, "Unknown user")
    return user


@router.get("/login")
async def login(response: Response):
    provider = get_auth_provider()
    state = secrets.token_urlsafe(24)
    if isinstance(provider, OIDCProvider):
        url = await provider.authorize_url_async(_redirect_uri(), state)
    else:
        url = provider.authorize_url(_redirect_uri(), state)
    redirect = RedirectResponse(url)
    redirect.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax")
    return redirect


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    expected_state = request.cookies.get(STATE_COOKIE)
    if not expected_state or expected_state != state:
        raise HTTPException(400, "Invalid OAuth state")
    provider = get_auth_provider()
    identity = await provider.exchange_code(code, _redirect_uri())
    user = await _upsert_user(db, identity)
    redirect = RedirectResponse(get_settings().app_url)
    redirect.delete_cookie(STATE_COOKIE)
    _set_session_cookie(redirect, user.id)
    return redirect


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "provider": user.provider,
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}
