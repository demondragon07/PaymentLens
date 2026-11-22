"""Runs the offline known-answer evaluation as a test."""
from scripts.run_eval import run


def test_known_answer_eval_offline():
    out = run(use_llm=False)
    failed = [(r["id"], {k: v for k, v in r["checks"].items() if not v}) for r in out["cases"] if not r["passed"]]
    assert not failed, failed
