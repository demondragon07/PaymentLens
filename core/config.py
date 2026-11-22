"""Project paths, constants and loaders for the YAML config and OpenAI settings."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("PAYMENTLENS_DB", str(ROOT / "data" / "paymentlens.duckdb")))
GROUND_TRUTH_PATH = ROOT / "data" / "ground_truth.json"
LOG_DIR = ROOT / "logs"
PROMPT_DIR = ROOT / "ai" / "prompts"

ALLOWED_TABLES = {"transactions", "transactions_raw", "merchants", "banks", "settlements"}
TERMINAL_STATUSES = ("SUCCESS", "FAILED")
VALID_STATUSES = ("SUCCESS", "FAILED", "PENDING", "USER_CANCELLED")


def _load_yaml(name: str) -> dict:
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def semantic() -> dict:
    return _load_yaml("metrics.yaml")


@lru_cache
def policies() -> dict:
    return _load_yaml("policies.yaml")


def limits() -> dict:
    return semantic()["limits"]


def openai_settings() -> dict:
    """Reads the OpenAI settings each time, so a key added to .env works after a restart."""
    return {
        "api_key": os.getenv("OPENAI_API_KEY") or None,
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
    }
