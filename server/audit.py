"""
Audit logging.

Every tool call gets recorded: who (api key id), what (tool + args),
when, and whether it succeeded. This is the piece that lets you answer
"what did the AI actually do to my database" after the fact — the
difference between a toy and something you could put in front of a
security review.
"""

import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

LOG_FILE = os.environ.get("LOG_FILE", str(PROJECT_ROOT / "logs" / "audit.log"))
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def log_call(caller: str, tool: str, args: dict, success: bool, detail: str = ""):
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "caller": caller,
        "tool": tool,
        "args": args,
        "success": success,
        "detail": detail,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")