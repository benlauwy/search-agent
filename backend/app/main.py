import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import files, sessions, settings, stream
from .auth import routes as auth_routes
from .config import get_settings
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.auth_provider != "dev" and s.secret_key == "dev-secret-change-me":
        raise RuntimeError("SA_SECRET_KEY must be set to a strong random value in production")
    await init_db()
    yield


app = FastAPI(title="search-agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().app_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(sessions.router)
app.include_router(stream.router)
app.include_router(files.router)
app.include_router(settings.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


# In the Docker deployment the frontend build is served by this process
# (hash-based routing, so index.html at / covers all client routes).
_static_dir = get_settings().static_dir
if _static_dir and os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
