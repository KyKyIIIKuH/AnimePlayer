"""Centralized global authentication state."""
import os
from app.core.utils import pathname
from dotenv import load_dotenv

# Ensure environment variables are loaded when auth is imported
load_dotenv(f"{pathname}/.env")

SHIKIMORI_TOKEN: str | None = os.getenv("SHIKIMORI_TOKEN")
