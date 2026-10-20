"""Load .env and pin Cognee's storage to the repo (not inside .venv)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")  # fallback: keys kept one level up (never overrides)
# Defaults: Claude for Cognee's LLM, local fastembed for embeddings (Anthropic has no embeddings API)
for k, v in {
    "LLM_PROVIDER": "anthropic",
    "LLM_MODEL": "anthropic/claude-haiku-5-5",
    "EMBEDDING_PROVIDER": "fastembed",
    "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
    "EMBEDDING_DIMENSIONS": "384",
}.items():
    os.environ.setdefault(k, v)
os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", str(ROOT / ".cognee_system"))
os.environ.setdefault("DATA_ROOT_DIRECTORY", str(ROOT / ".data_storage"))
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
