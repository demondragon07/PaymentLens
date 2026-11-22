"""Hand-checked tests for the decomposition, counterfactual and statistics."""
import pandas as pd
import pytest

from analytics.decomposition import decompose, segment_table, simpson_check
from analytics.stats import two_proportion_z, wilson_ci


def _seg(rows):
    df = pd.DataFrame(rows, columns=["period", "seg", "numerator", "denominator"])
    return segment_table(df, ["seg"])


def test_pure_mix_shift_example():
    # A: 95% both periods, B: 80% both periods; traffic moves from A to B
    seg = _seg([("previous", "A", 760, 800), ("previous", "B", 160, 200),
                ("current", "A", 475, 500), ("current", "B", 400, 500)])
    d = decompose(seg, ["seg"], min_n=1)
    assert d.R0 == pytest.approx(0.92)
    assert d.R1 == pytest.approx(0.875)
    assert d.rate_effect == pytest.approx(0.0)
    assert d.mix_effect == pytest.approx(-0.045)
    assert d.counterfactual_rate == pytest.approx(0.92)       # old mix, new rates = old rate
    assert d.reconciles


def test_mix_and_rate_example_reconciles():
    # same, but B also deteriorates 80% -> 70%
    seg = _seg([("previous", "A", 760, 800), ("previous", "B", 160, 200),
                ("current", "A", 475, 500), ("current", "B", 350, 500)])
    d = decompose(seg, ["seg"], min_n=1)
    assert d.delta == pytest.approx(-0.095)
    assert d.rate_effect == pytest.approx(-0.035)              # 0.35 * -0.10
    assert d.mix_effect == pytest.approx(-0.060)
    assert d.rate_effect + d.mix_effect == pytest.approx(d.delta, abs=1e-12)
    assert d.counterfactual_rate == pytest.approx(0.90)        # 0.8*0.95 + 0.2*0.70
    assert d.cf_rate_effect == pytest.approx(-0.02)
    assert d.cf_mix_effect == pytest.approx(-0.075)
    assert d.interaction == pytest.approx(-0.03)               # 0.3 * -0.10
    # the two ways of splitting differ by exactly half the interaction term
    assert d.rate_effect == pytest.approx(d.cf_rate_effect + d.interaction / 2)


def test_segment_missing_in_one_period():
    seg = _seg([("previous", "A", 90, 100), ("current", "A", 90, 100), ("current", "C", 50, 100)])
    d = decompose(seg, ["seg"], min_n=1)
    assert d.reconciles


def test_simpson_detected_when_all_segments_improve():
    seg = _seg([("previous", "A", 9400, 10000), ("previous", "B", 1600, 2000),
                ("current", "A", 6040, 6400), ("current", "B", 4950, 6000)])
    d = decompose(seg, ["seg"], min_n=100)
    z, p = two_proportion_z(11000, 12000, 10990, 12400)
    assert d.delta < 0
    assert (d.segments.rate_change > 0).all()
    assert simpson_check(d, p)["detected"]


def test_wilson_and_ztest_known_values():
    lo, hi = wilson_ci(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    z, p = two_proportion_z(900, 1000, 850, 1000)
    assert z < 0 and p < 0.01
