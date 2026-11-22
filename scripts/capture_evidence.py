"""Runs the demo questions and saves their outputs and charts to docs/evidence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ai.intent_parser import build_system_prompt  # noqa: E402
from core.pipeline import PaymentLens  # noqa: E402

OUT = ROOT / "docs" / "evidence"
BLUE, ORANGE, RED, GRAY = "#2a78d6", "#eb6834", "#e34948", "#8a8984"

QUESTIONS = {
    "main": ("Why did payment success rate fall last week?", "business_analyst"),
    "simpson": ("Why did success rate fall in the week of Oct 26 compared with the week before?", "business_analyst"),
    "raw": ("What was success rate last week using raw data?", "admin"),
    "breakdown": ("Show payment success rate by bank last week compared with the previous week", "business_analyst"),
    "denied": ("Show individual merchants with their settlement bank account details", "business_analyst"),
    "alternative": ("Show payment success rate by merchant for last week", "business_analyst"),
    "regional": ("Why did success rate fall last week?", "regional_analyst_north"),
    "recon": ("Reconcile last week's successful transactions with settlements", "admin"),
    "unsupported": ("Did Zenith Bank intentionally reject our transactions?", "admin"),
    "budget": ("Show success rate for the last 120 days", "admin"),
    "order": ("What was order conversion last week?", "business_analyst"),
}


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, float) and o != o:
        return None
    return o if isinstance(o, (str, int, float, bool, type(None))) else str(o)


def dump(res) -> dict:
    a = res.analysis
    keep = {k: a.get(k) for k in ("metric_label", "kind", "overall", "decomposition", "drivers", "simpson", "drilldown",
                                  "reconciliation", "grain", "trend_summary", "breakdown_top", "llm_meta")}
    keep["bank_view"] = (a.get("dimension_views") or {}).get("bank")
    rq = res.resolved
    return clean({
        "question": res.question, "role": res.role, "status": res.status, "message": res.message,
        "parser": res.parser_used, "parser_notes": res.parser_notes,
        "intent": res.intent.model_dump() if res.intent else None,
        "resolved": None if not rq else {"metric": rq.metric, "analysis_type": rq.analysis_type,
                                         "current": rq.current.pretty(), "previous": rq.previous.pretty() if rq.previous else None,
                                         "filters": rq.filters, "dimensions": rq.dimensions, "source": rq.source_table,
                                         "assumptions": rq.assumptions, "notices": rq.notices},
        "policy": {k: v for k, v in (res.policy or {}).items()},
        "queries": [{"id": q.id, "purpose": q.purpose, "status": q.status, "rows": q.rows, "ms": q.elapsed_ms,
                     "cache_hit": q.cache_hit, "tables": q.tables, "sql": q.sql, "executed_sql": q.executed_sql,
                     "checks": q.checks} for q in res.queries],
        "facts": [{"id": f.id, "text": f.text, "queries": f.query_ids} for f in res.facts],
        "narrative": res.narrative.model_dump() if res.narrative else None,
        "confidence": res.confidence, "dq": {k: v for k, v in (res.dq or {}).items()},
        "trace": [t.__dict__ for t in res.trace], "analysis": keep,
    })


def waterfall_png(d: dict, path: Path, title: str) -> None:
    vals = [d["R0"] * 100, d["mix_effect"] * 100, d["rate_effect"] * 100, d["R1"] * 100]
    labels = ["Previous\nrate", "Traffic-mix\neffect", "Within-segment\nrate effect", "Current\nrate"]
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)
    bottom = [0, vals[0] + min(vals[1], 0), vals[0] + vals[1] + min(vals[2], 0), 0]
    heights = [vals[0], abs(vals[1]), abs(vals[2]), vals[3]]
    colors = [GRAY, RED if vals[1] < 0 else BLUE, RED if vals[2] < 0 else BLUE, GRAY]
    ax.bar(labels, heights, bottom=bottom, color=colors, width=0.55, edgecolor="white", linewidth=2)
    txt = [f"{vals[0]:.2f}%", f"{vals[1]:+.2f}pp", f"{vals[2]:+.2f}pp", f"{vals[3]:.2f}%"]
    for i, t in enumerate(txt):
        ax.text(i, bottom[i] + heights[i] + 0.15, t, ha="center", fontsize=9)
    lo = min(vals[0], vals[3]) - 2.5
    ax.set_ylim(lo, max(vals[0], vals[3]) + 1.2)
    ax.set_ylabel("Success rate (%)")
    ax.set_title(title, fontsize=10, loc="left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def trend_png(res, path: Path) -> None:
    t = res.tables["trend"].copy()
    t["day"] = pd.to_datetime(t["day"])
    t = t.sort_values("day")
    d = res.tables["drill_daily"].copy()
    d["day"] = pd.to_datetime(d["day"])
    d = d.sort_values("day")
    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=200)
    ax.plot(t.day, t.value * 100, color=BLUE, marker="o", ms=4, lw=2, label="All traffic")
    ax.plot(d.day, d.value * 100, color=ORANGE, marker="o", ms=4, lw=2, label="Nova Bank | UPI")
    ax.axvspan(pd.Timestamp("2026-11-09") - pd.Timedelta(hours=12), pd.Timestamp("2026-11-15") + pd.Timedelta(hours=12),
               color=GRAY, alpha=0.12, lw=0)
    ax.text(pd.Timestamp("2026-11-09"), 101, "current week", fontsize=8, color="#52514e")
    ax.set_ylabel("Daily success rate (%)")
    ax.set_ylim(60, 103)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    ax.set_title("Daily payment success rate, 02-15 Nov 2026 (real query output)", fontsize=10, loc="left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def contrib_png(seg: pd.DataFrame, path: Path) -> None:
    s = seg.reindex(seg.contribution.abs().sort_values(ascending=False).index).head(8).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=200)
    ax.barh(s.segment, s.rate_effect * 100, color=BLUE, label="Rate effect", height=0.55)
    ax.barh(s.segment, s.mix_effect * 100, left=[(r if (r < 0) == (m < 0) else 0) for r, m in zip(s.rate_effect * 100, s.mix_effect * 100)],
            color=ORANGE, label="Mix effect", height=0.55)
    ax.axvline(0, color="#52514e", lw=0.8)
    ax.set_xlabel("Contribution to change (pp)")
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    ax.set_title("Largest contributors, bank x payment method (real query output)", fontsize=10, loc="left")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pl = PaymentLens()
    results = {}
    for key, (q, role) in QUESTIONS.items():
        res = pl.run(q, role, use_llm=False)
        results[key] = res
        (OUT / f"{key}.json").write_text(json.dumps(dump(res), indent=2), encoding="utf-8")
        print(f"{key:12s} {res.status:11s} queries={len(res.queries):2d}  {q}")
    main = results["main"]
    main.tables["segments"].to_csv(OUT / "main_segments.csv", index=False)
    results["simpson"].tables["segments"].to_csv(OUT / "simpson_segments.csv", index=False)
    waterfall_png(main.analysis["decomposition"], OUT / "waterfall_main.png", "Week of 09 Nov vs week of 02 Nov (symmetric decomposition)")
    waterfall_png(results["simpson"].analysis["decomposition"], OUT / "waterfall_simpson.png",
                  "Week of 26 Oct vs week of 19 Oct: Simpson's paradox")
    trend_png(main, OUT / "trend_main.png")
    contrib_png(main.tables["segments"], OUT / "contrib_main.png")
    fresh = main.dq["freshness"]
    prompt = build_system_prompt(pl.catalog(), pl.as_of, str(fresh["first_day"]), str(fresh["last_complete_day"]))
    (OUT / "intent_system_prompt_rendered.md").write_text(prompt, encoding="utf-8")
    print(f"Evidence written to {OUT}")


if __name__ == "__main__":
    main()
