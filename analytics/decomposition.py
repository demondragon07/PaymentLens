"""Splits a rate change into traffic-mix and within-segment effects, plus counterfactual and Simpson check."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from analytics.stats import two_proportion_z, wilson_ci


@dataclass
class Decomposition:
    keys: list[str]
    R0: float
    R1: float
    delta: float
    rate_effect: float
    mix_effect: float
    interaction: float
    counterfactual_rate: float
    cf_rate_effect: float
    cf_mix_effect: float
    residual: float
    segments: pd.DataFrame

    @property
    def reconciles(self) -> bool:
        return abs(self.residual) < 1e-9


def segment_table(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Adds up successes and attempts for each segment in both periods (0 if a period has no data)."""
    g = df.groupby(["period", *keys], dropna=False)[["numerator", "denominator"]].sum().reset_index()
    prev = g[g.period == "previous"].drop(columns="period").rename(columns={"numerator": "s0", "denominator": "n0"})
    cur = g[g.period == "current"].drop(columns="period").rename(columns={"numerator": "s1", "denominator": "n1"})
    seg = pd.merge(prev, cur, on=keys, how="outer").fillna({"s0": 0, "n0": 0, "s1": 0, "n1": 0})
    for c in ["s0", "n0", "s1", "n1"]:
        seg[c] = seg[c].astype(int)
    return seg


def decompose(seg: pd.DataFrame, keys: list[str], min_n: int = 200, alpha: float = 0.05) -> Decomposition:
    s = seg.copy()
    N0, N1 = s.n0.sum(), s.n1.sum()
    if N0 == 0 or N1 == 0:
        raise ValueError("Both periods need data for a decomposition")
    R0, R1 = s.s0.sum() / N0, s.s1.sum() / N1
    s["w0"] = s.n0 / N0
    s["w1"] = s.n1 / N1
    s["r0"] = np.where(s.n0 > 0, s.s0 / s.n0.where(s.n0 > 0, 1), np.nan)
    s["r1"] = np.where(s.n1 > 0, s.s1 / s.n1.where(s.n1 > 0, 1), np.nan)
    # if a segment has no data in one period, reuse the other period's rate (so it only adds to the mix effect)
    s["r0"] = s.r0.fillna(s.r1)
    s["r1"] = s.r1.fillna(s.r0)
    Rbar = (R0 + R1) / 2
    s["rate_effect"] = (s.w0 + s.w1) / 2 * (s.r1 - s.r0)
    s["mix_effect"] = ((s.r0 + s.r1) / 2 - Rbar) * (s.w1 - s.w0)
    s["contribution"] = s.rate_effect + s.mix_effect
    s["rate_change"] = s.r1 - s.r0
    s["share_change"] = s.w1 - s.w0
    pv, lo, hi = [], [], []
    for row in s.itertuples():
        pv.append(two_proportion_z(row.s0, row.n0, row.s1, row.n1)[1])
        a, b = wilson_ci(row.s1, row.n1)
        lo.append(a)
        hi.append(b)
    s["p_value"] = pv
    s["r1_ci_low"], s["r1_ci_high"] = lo, hi
    s["enough_volume"] = (s.n0 >= min_n) & (s.n1 >= min_n)
    s["significant"] = s.enough_volume & (s.p_value < alpha)
    s["segment"] = s[keys].astype(str).agg(" | ".join, axis=1)

    rate, mix = float(s.rate_effect.sum()), float(s.mix_effect.sum())
    cf = float((s.w0 * s.r1).sum())
    inter = float(((s.w1 - s.w0) * (s.r1 - s.r0)).sum())
    delta = R1 - R0
    return Decomposition(
        keys=keys, R0=float(R0), R1=float(R1), delta=float(delta),
        rate_effect=rate, mix_effect=mix, interaction=inter,
        counterfactual_rate=cf, cf_rate_effect=cf - R0, cf_mix_effect=R1 - cf,
        residual=float(delta - rate - mix),
        segments=s.sort_values("contribution").reset_index(drop=True),
    )


def top_drivers(d: Decomposition, n: int = 3) -> dict[str, pd.DataFrame]:
    seg = d.segments
    neg = d.delta < 0
    rate = seg.sort_values("rate_effect", ascending=neg).head(n)
    mix = seg.sort_values("mix_effect", ascending=neg).head(n)
    return {"rate": rate, "mix": mix}


def simpson_check(d: Decomposition, overall_p: float, alpha: float = 0.05) -> dict:
    """Flags Simpson's paradox: the total moved one way while no big segment moved that way."""
    seg = d.segments[d.segments.enough_volume]
    if seg.empty or not (overall_p < alpha) or d.delta == 0:
        return {"detected": False}
    direction = np.sign(d.delta)
    same_dir_sig = seg[(np.sign(seg.rate_change) == direction) & seg.significant]
    opposite = int((np.sign(seg.rate_change) == -direction).sum())
    detected = same_dir_sig.empty and opposite >= max(1, len(seg) // 2)
    return {
        "detected": bool(detected),
        "segments_checked": int(len(seg)),
        "segments_moving_opposite": opposite,
        "segments_significant_same_direction": int(len(same_dir_sig)),
        "message": (
            f"Aggregate rate {'fell' if direction < 0 else 'rose'} {abs(d.delta) * 100:.2f}pp although "
            f"{opposite} of {len(seg)} {' x '.join(d.keys)} segments moved the other way and none moved "
            f"significantly in the same direction. This is a mix-shift (Simpson's paradox) pattern."
        ) if detected else "",
    }


def additive_breakdown(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """For totals like GMV or counts: how much each segment changed and its share of the total change."""
    g = df.groupby(["period", *keys])["value"].sum().unstack("period").fillna(0)
    for c in ("previous", "current"):
        if c not in g:
            g[c] = 0.0
    g["change"] = g["current"] - g["previous"]
    total = g["change"].sum()
    g["share_of_change"] = g["change"] / total if total else np.nan
    return g.reset_index().sort_values("change")
