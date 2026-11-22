"""Calls OpenAI with a Pydantic schema and turns any failure into LLMUnavailable."""
from __future__ import annotations

import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from core.config import openai_settings

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(Exception):
    pass


def llm_configured() -> bool:
    return bool(openai_settings()["api_key"])


def structured_call(system: str, user: str, schema: type[T]) -> tuple[T, dict]:
    s = openai_settings()
    if not s["api_key"]:
        raise LLMUnavailable("no OPENAI_API_KEY configured")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=s["api_key"], timeout=s["timeout"], max_retries=1)
    except Exception as e:  # pragma: no cover - only if the OpenAI library is missing or broken
        raise LLMUnavailable(f"OpenAI client could not be created: {type(e).__name__}") from e

    last_err = None
    for attempt in (1, 2):  # try once more if the AI's answer does not match the schema
        t0 = time.perf_counter()
        try:
            resp = client.responses.parse(model=s["model"], instructions=system, input=user, text_format=schema)
            parsed = resp.output_parsed
            if parsed is None:
                raise LLMUnavailable("model returned no parsable output (possible refusal)")
            usage = getattr(resp, "usage", None)
            meta = {"model": s["model"], "attempts": attempt, "latency_ms": round((time.perf_counter() - t0) * 1000),
                    "input_tokens": getattr(usage, "input_tokens", None), "output_tokens": getattr(usage, "output_tokens", None)}
            return parsed, meta
        except ValidationError as e:
            last_err = f"schema validation failed: {str(e).splitlines()[0][:120]}"
            continue
        except LLMUnavailable:
            raise
        except Exception as e:  # any OpenAI or network error
            raise LLMUnavailable(f"{type(e).__name__}: {str(e)[:160]}") from e
    raise LLMUnavailable(last_err or "unknown error")
