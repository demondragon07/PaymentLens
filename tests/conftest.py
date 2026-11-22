"""Shared pytest fixtures: the pipeline, ground truth, and LLM disabled."""
import json

import pytest

from core.config import GROUND_TRUTH_PATH
from core.pipeline import PaymentLens


@pytest.fixture(scope="session")
def pl() -> PaymentLens:
    return PaymentLens()


@pytest.fixture(scope="session")
def gt() -> dict:
    return json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Turns off the AI in tests so they never call the internet."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
