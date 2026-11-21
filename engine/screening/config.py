import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = Path(os.environ.get("SCREENING_DATA", ROOT / "processed"))
TABLES = PROCESSED / "tables"
REFERENCE = PROCESSED / "reference"
OUTPUTS = ROOT / "outputs"
CACHE = ROOT / ".cache"

# Grok (xAI) settings. The API is OpenAI-compatible.
XAI_API_KEY = os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
XAI_BASE_URL = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-4-fast-non-reasoning")
