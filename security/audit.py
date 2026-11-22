"""Append-only audit log of every query decision."""
from __future__ import annotations

import json
from datetime import datetime

from core.config import LOG_DIR

AUDIT_FILE = LOG_DIR / "audit.jsonl"


def log_event(**fields) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), **fields}
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def recent(n: int = 200) -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()[-n:]
    return [json.loads(x) for x in reversed(lines) if x.strip()]
