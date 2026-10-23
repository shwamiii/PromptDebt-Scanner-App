"""PromptDebt Scanner API. Also serves the web app from ../web when it exists.

Run locally from the api folder:  uvicorn app.main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registers the tables with Base)
from .config import CORS_ORIGINS, WEB_DIR
from .db import Base, engine
from .errors import register_error_handlers
from .routes import identity, scans, triage, watchlist

Base.metadata.create_all(engine)

app = FastAPI(title="PromptDebt Scanner API", version="1.0.0")
register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith(("/docs", "/openapi.json")):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
    if not request.url.path.startswith("/api/"):
        # Web app files: always check for a newer version, so a deploy shows up
        # immediately instead of mixing old and new JavaScript.
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}


for router in (identity.router, scans.router, watchlist.router, triage.router):
    app.include_router(router)

if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
