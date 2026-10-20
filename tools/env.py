"""Load .env and pin Cognee's storage to the repo (not inside .venv)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", str(ROOT / ".cognee_system"))
os.environ.setdefault("DATA_ROOT_DIRECTORY", str(ROOT / ".data_storage"))
os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
