"""Settings, read from environment variables (and a local .env file if present)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT_DIR / "web"

load_dotenv(ROOT_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./promptdebt.db"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or None
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
TRUST_PROXY = os.getenv("TRUST_PROXY") == "1"

# Optional AI review: any OpenAI-compatible chat completions API (e.g. Groq,
# OpenRouter). With these unset the app works fully and the review is unavailable.
LLM_BASE_URL = (os.getenv("LLM_BASE_URL") or "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY") or ""
LLM_MODEL = os.getenv("LLM_MODEL") or ""
LLM_TIMEOUT_SECONDS = 30

# Requests per minute, per IP address.
SCAN_RATE_LIMIT = 10
IDENTITY_RATE_LIMIT = 5
REVIEW_RATE_LIMIT = 5
