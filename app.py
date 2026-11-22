"""Streamlit UI for PaymentLens: ask a question, see the answer, evidence, SQL Explorer and audit log."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ai.llm_client import llm_configured
from core.config import limits, openai_settings, policies, semantic
from core.pipeline import PaymentLens
from security import audit
from security.policy import role_labels

st.set_page_config(page_title="PaymentLens", page_icon="🔎", layout="wide")

# Chart colours: blue and orange for two series, blue/red for up/down, gray for the baseline
BLUE, ORANGE, RED, GRAY = "#2a78d6", "#eb6834", "#e34948", "#8a8984"
INK, SLATE = "#13203A", "#56667D"
STATUS = {"ANSWERED": "Answered", "DENIED": "Access denied", "BLOCKED": "Blocked",
          "UNSUPPORTED": "Cannot answer from this data", "ERROR": "Error"}

# A light 'frosted glass' look for a business app: see-through panels on a soft background,
# soft navy shadows, rounder corners for more important boxes, and no shiny buttons.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&display=swap');
:root {
  --mist:#EAEFF5; --ink:#13203A; --slate:#56667D; --teal:#0E7C74; --teal-deep:#0A5F59;
  --glass:rgba(255,255,255,.60); --glass-strong:rgba(255,255,255,.80); --edge:rgba(255,255,255,.85);
  --hair:rgba(19,32,58,.10); --shadow:0 1px 2px rgba(19,32,58,.05), 0 10px 28px -16px rgba(19,32,58,.28);
}
html, body, .stApp, .stApp button, .stApp input, .stApp textarea, [data-testid="stMarkdownContainer"] {
  font-family:'Geist', ui-sans-serif, system-ui, sans-serif !important;
}
.stApp { background:var(--mist); color:var(--ink); }
.stApp::before {
  content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
  background:
    radial-gradient(42rem 30rem at 8% -8%, rgba(14,124,116,.17), transparent 70%),
    radial-gradient(38rem 30rem at 96% 4%, rgba(70,92,190,.13), transparent 70%),
    radial-gradient(48rem 32rem at 55% 112%, rgba(14,124,116,.09), transparent 70%);
}
[data-testid="stHeader"] { background:transparent; }
.block-container { padding-top:3.8rem; max-width:1320px; position:relative; z-index:1; }

/* sidebar: one long glass sheet */
[data-testid="stSidebar"] > div:first-child {
  background:rgba(255,255,255,.52); backdrop-filter:blur(20px) saturate(140%); -webkit-backdrop-filter:blur(20px) saturate(140%);
  border-right:1px solid var(--edge);
}
.pl-brand { display:flex; align-items:center; gap:.55rem; font-weight:650; font-size:1.18rem; letter-spacing:-.01em; color:var(--ink); }
.pl-brand i { width:.7rem; height:.7rem; border-radius:3px; background:var(--teal); display:inline-block; }

/* hero */
.pl-hero h1 { font-size:2rem; font-weight:620; letter-spacing:-.025em; line-height:1.15; color:var(--ink); margin:0 0 .35rem 0; padding:0; }
.pl-hero p { color:var(--slate); font-size:1rem; max-width:62ch; margin:0 0 1.1rem 0; }

/* the ask panel is the one bold element */
[data-testid="stForm"] {
  background:var(--glass-strong); backdrop-filter:blur(18px) saturate(150%); -webkit-backdrop-filter:blur(18px) saturate(150%);
  border:1px solid var(--edge); border-radius:18px; box-shadow:var(--shadow); padding:1.1rem 1.2rem;
}
[data-testid="stForm"] input { font-size:1.05rem !important; min-height:3rem; }
[data-testid="stTextInputRootElement"] { border-radius:10px !important; border:1px solid var(--hair) !important; background:rgba(255,255,255,.9) !important; }
[data-testid="stTextInputRootElement"]:focus-within { border-color:var(--teal) !important; box-shadow:0 0 0 3px rgba(14,124,116,.16); }

/* buttons */
.stButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius:10px; border:1px solid var(--hair); background:var(--glass); color:var(--ink);
  backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); font-weight:500; box-shadow:none;
}
.stButton > button:hover { border-color:rgba(14,124,116,.45); color:var(--teal-deep); background:rgba(255,255,255,.78); }
.stButton > button:focus-visible, [data-testid="stFormSubmitButton"] > button:focus-visible { outline:2px solid var(--teal); outline-offset:2px; }
[data-testid="stFormSubmitButton"] > button, .stButton > button[kind="primary"] {
  background:var(--teal); border-color:var(--teal); color:#fff; padding:0 1.4rem; min-height:2.6rem;
}
[data-testid="stFormSubmitButton"] > button:hover, .stButton > button[kind="primary"]:hover { background:var(--teal-deep); border-color:var(--teal-deep); color:#fff; }

/* tabs */
[data-baseweb="tab-list"] { gap:1.4rem; border-bottom:1px solid var(--hair); }
[data-baseweb="tab"] { color:var(--slate); font-weight:500; background:transparent; }
[data-baseweb="tab"][aria-selected="true"] { color:var(--ink); }
[data-baseweb="tab-highlight"] { background:var(--teal) !important; }

/* glass panels: lighter than the ask panel */
[data-testid="stMetric"], [data-testid="stExpander"] details, [data-testid="stPlotlyChart"], .pl-card {
  background:var(--glass); backdrop-filter:blur(14px) saturate(140%); -webkit-backdrop-filter:blur(14px) saturate(140%);
  border:1px solid var(--edge); border-radius:14px; box-shadow:var(--shadow);
}
[data-testid="stMetric"] { padding:.9rem 1rem; }
[data-testid="stMetricLabel"] p { color:var(--slate); font-size:.84rem; }
[data-testid="stMetricValue"] { font-weight:600; letter-spacing:-.02em; font-variant-numeric:tabular-nums; }
[data-testid="stPlotlyChart"] { padding:.4rem .6rem; }
[data-testid="stExpander"] details { overflow:hidden; }
[data-testid="stExpander"] summary { font-weight:600; }
[data-testid="stAlert"] { border-radius:12px; backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px); }
[data-testid="stDataFrame"] { border-radius:12px; overflow:hidden; border:1px solid var(--hair); background:rgba(255,255,255,.7); }
[data-testid="stCodeBlock"] pre { border-radius:10px; }

/* answer cards: slim top rule carries the meaning, no all-caps labels */
.pl-card { padding:1rem 1.1rem; margin-bottom:.6rem; height:100%; border-top:3px solid var(--rule); }
.pl-card.fact { --rule:#2A6FDB; } .pl-card.hyp { --rule:#B7791F; } .pl-card.rec { --rule:#1F8A5B; }
.pl-card h4 { margin:0 0 .5rem 0; font-size:.98rem; font-weight:600; color:var(--ink); letter-spacing:-.005em; }
.pl-card ul { padding-left:.95rem; margin:0; } .pl-card li { margin:0 0 .5rem 0; padding-left:0; line-height:1.5; font-size:.88rem; }
.pl-tag { display:inline-block; padding:0 .45rem; border-radius:6px; font-size:.74rem; border:1px solid var(--hair); color:var(--slate); background:rgba(255,255,255,.7); margin-right:.35rem; }
.pl-small { font-size:.88rem; color:var(--ink); }
.pl-summary { font-size:1.22rem; font-weight:600; letter-spacing:-.015em; line-height:1.35; max-width:80ch; margin:.4rem 0 .9rem 0; color:var(--ink); }
@media (prefers-reduced-motion: reduce) { * { transition:none !important; animation:none !important; } }
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_pl() -> PaymentLens:
    return PaymentLens()


def pct(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{x * 100:.2f}%"


def pp(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{x * 100:+.2f}pp"


def fig_style(fig: go.Figure, h: int = 320) -> go.Figure:
    unified = bool(fig.data) and fig.data[0].type == "scatter"
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=44, b=10), title_font=dict(size=14, color=INK),
                      font=dict(family="Geist, system-ui, sans-serif", color=SLATE, size=12),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", yanchor="bottom", y=-0.32, x=0),
                      hoverlabel=dict(bgcolor="white", bordercolor="rgba(19,32,58,.15)", font=dict(color=INK)),
                      hovermode="x unified" if unified else "closest")
    fig.update_xaxes(showgrid=False, linecolor="rgba(19,32,58,.15)")
    fig.update_yaxes(gridcolor="rgba(19,32,58,.08)", zeroline=False)
    return fig


pl = get_pl()
labels = role_labels()

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("<div class='pl-brand'><i></i>PaymentLens</div>", unsafe_allow_html=True)
    st.caption("Payment performance analysis with the evidence attached")
    role = st.selectbox("Signed in as (simulated role)", list(labels), format_func=lambda r: labels[r], index=1)
    has_key = llm_configured()
    use_llm = st.toggle("Use OpenAI for understanding & narrative", value=has_key, disabled=not has_key)
    if has_key:
        st.success(f"OpenAI connected (model `{openai_settings()['model']}`)")
    else:
        st.info("No OpenAI key in .env. Questions are read by the offline parser.")
    st.divider()
    st.markdown(f"**Data as of:** `{pl.as_of}`")
    st.caption("Synthetic dataset · 4 weeks · DuckDB opened read-only")
    if st.button("Clear query cache"):
        pl.ex.clear_cache()
        st.toast("Cache cleared")

EXAMPLES = {
    "Why did success fall?": "Why did payment success rate fall last week?",
    "Mix-shift week (Oct 26)": "Why did success rate fall in the week of Oct 26 compared with the week before?",
    "By bank vs previous": "Show payment success rate by bank last week compared with the previous week",
    "Raw vs trusted data": "What was success rate last week using raw data?",
    "Reconcile settlements": "Reconcile last week's successful transactions with settlements",
    "Merchant bank accounts": "Show individual merchants with their settlement bank account details",
    "Bank's intent": "Did Zenith Bank intentionally reject our transactions?",
    "120-day query": "Show success rate for the last 120 days",
}

tab_ask, tab_sql, tab_audit, tab_def = st.tabs(["Ask PaymentLens", "SQL Explorer", "Audit log", "Definitions"])


# ----------------------------------------------------------------------------- renderers
def render_status(res) -> None:
    if res.status == "ANSWERED":
        return
    label = STATUS.get(res.status, res.status)
    box = st.error if res.status in ("DENIED", "BLOCKED", "ERROR") else st.warning
    box(f"**{label}.** {res.message}")
    if res.status == "DENIED" and res.policy:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Your role can see**")
            for s in res.policy.get("allowed_scope", []):
                st.markdown(f"- {s}")
        with c2:
            st.markdown("**Restricted for your role**")
            st.markdown("- Merchant settlement bank accounts\n- Merchant contact details (PII)")
        if res.policy.get("alternative"):
            st.info(res.policy["alternative"])


def render_understanding(res) -> None:
    rq, it = res.resolved, res.intent
    with st.expander("How I understood your question", expanded=True):
        c1, c2, c3 = st.columns([1.2, 1.2, 1])
        with c1:
            st.markdown(f"**Metric:** {rq.metric_spec['label']}")
            if rq.metric_spec["kind"] == "ratio":
                st.markdown(f"<span class='pl-small'>Numerator: {rq.metric_spec['numerator']}<br>"
                            f"Denominator: {rq.metric_spec['denominator']}</span>", unsafe_allow_html=True)
            st.markdown(f"**Analysis:** `{rq.analysis_type}` · **Source:** `{rq.source_table}`")
        with c2:
            st.markdown(f"**Current period:** {rq.current.pretty()}")
            st.markdown(f"**Comparison:** {rq.previous.pretty() if rq.previous else '—'}")
            st.markdown(f"**Filters:** {rq.filters or 'none'} · **Dimensions:** {rq.dimensions or 'auto'}")
        with c3:
            st.markdown(f"**Parser:** {'OpenAI' if res.parser_used == 'llm' else 'rule-based'}")
            conf = res.confidence
            st.markdown(f"**Confidence:** {conf.get('level', '–')} ({conf.get('score', '–')}/100)")
            for r in conf.get("reasons", [])[:3]:
                st.markdown(f"<span class='pl-small'>· {r}</span>", unsafe_allow_html=True)
        if it.ambiguities or rq.assumptions or rq.notices or res.parser_notes:
            st.markdown("**What I had to decide**")
            for a in it.ambiguities:
                st.markdown(f"- *Ambiguous:* {a}")
            for a in rq.assumptions:
                st.markdown(f"- *Assumed:* {a}")
            for a in rq.notices:
                st.markdown(f"- *Access:* {a}")
            for a in res.parser_notes:
                st.markdown(f"- *Note:* {a}")


def render_kpis(res) -> None:
    a = res.analysis
    ov = a.get("overall") or {}
    if a.get("reconciliation"):
        rc = a["reconciliation"]
        c = st.columns(4)
        c[0].metric("Successful amount (INR)", f"{rc['successful_amount']:,.0f}")
        c[1].metric("Settled gross (INR)", f"{rc['settled_gross_amount']:,.0f}")
        c[2].metric("Gap (INR)", f"{rc['gap_amount']:,.0f}", f"{rc['gap_pct']:.2f}% of successful", delta_color="off")
        c[3].metric("Identity reconciles", "Yes" if rc["identity_holds"] else "No")
        return
    if not ov.get("current"):
        return
    ratio = a.get("kind") == "ratio"
    fmt = pct if ratio else (lambda x: f"{x:,.0f}")
    c = st.columns(4)
    if ov.get("previous"):
        p0 = res.resolved.previous
        c[0].metric(f"Previous ({p0.start:%d %b}–{p0.end:%d %b})", fmt(ov["previous"]["value"]))
    delta = None
    if "delta" in ov:
        delta = pp(ov["delta"]) if ratio else f"{ov['delta']:,.0f}"
    p1 = res.resolved.current
    c[1].metric(f"Current ({p1.start:%d %b}–{p1.end:%d %b})", fmt(ov["current"]["value"]), delta)
    if ratio and ov.get("p_value") is not None:
        c[2].metric("Is the change real?", "p < 0.001" if ov["p_value"] < 0.001 else f"p = {ov['p_value']:.3f}",
                    "significant" if ov["p_value"] < 0.05 else "may be noise", delta_color="off")
    elif ratio:
        lo, hi = ov["current"]["ci"]
        c[2].metric("95% confidence interval", f"{pct(lo)} – {pct(hi)}")
    c[3].metric("Answer confidence", res.confidence.get("level", "–"), f"{res.confidence.get('score', 0)}/100", delta_color="off")


def render_dq_banner(res) -> None:
    dq = res.dq or {}
    imp = dq.get("raw_vs_trusted")
    warns = [c for c in dq.get("checks", []) if c["severity"] == "warning"]
    if not warns:
        return
    lines = [f"**Data-quality warnings ({len(warns)}).** Handled before the trusted metric was computed:"]
    for c in warns:
        lines.append(f"- **{c['check']}:** {c['detail']} _{c['handling']}_")
    if imp and abs(imp["difference_pp"]) >= 0.01:
        lines.append(f"- **Impact on the answer:** raw data gives **{pct(imp['raw_rate'])}**, trusted data gives "
                     f"**{pct(imp['trusted_rate'])}** ({imp['difference_pp']:+.2f}pp). The trusted value is used.")
    st.warning("\n".join(lines))


def render_narrative(res) -> None:
    n = res.narrative
    if not n:
        return
    st.markdown(f"<p class='pl-summary'>{n.summary}</p>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        shown = n.observed[:5]
        more = len(n.observed) - len(shown)
        items = "".join(f"<li>{o}</li>" for o in shown)
        tail = f"<p class='pl-small'>+{more} more facts in the Evidence &amp; SQL tab</p>" if more > 0 else ""
        st.markdown(f"<div class='pl-card fact'><h4>What the data shows</h4><ul class='pl-small'>{items}</ul>{tail}</div>", unsafe_allow_html=True)
    with c2:
        items = "".join(f"<li><span class='pl-tag'>confidence: {h.confidence}</span>{h.text}"
                        f"<br><span class='pl-small'>evidence: {', '.join(h.evidence) or '—'}</span></li>" for h in n.hypotheses)
        items = items or "<li>No hypothesis is warranted by the data for this question.</li>"
        st.markdown(f"<div class='pl-card hyp'><h4>Possible explanations (not proven)</h4><ul class='pl-small'>{items}</ul></div>", unsafe_allow_html=True)
    with c3:
        items = "".join(f"<li>{r}</li>" for r in n.recommendations)
        st.markdown(f"<div class='pl-card rec'><h4>Recommended next steps</h4><ul class='pl-small'>{items}</ul></div>", unsafe_allow_html=True)
    g = n.grounding or {}
    st.caption(f"Narrative source: {'OpenAI, passed the number-grounding check' if n.generated_by == 'llm' else 'template built directly from computed facts'}"
               + ("" if g.get("passed", True) else f" · an LLM draft was rejected: {g.get('unmatched_numbers') or g.get('invalid_fact_ids')}"))


def chart_trend(df: pd.DataFrame, title: str, ratio: bool, baseline: float | None = None) -> go.Figure:
    d = df.copy()
    d["day"] = pd.to_datetime(d["day"])
    agg = {"numerator": "sum", "denominator": "sum"} if ratio else {"value": "sum"}
    d = d.groupby(["period", "day"]).agg(agg).reset_index()
    if ratio:
        d["value"] = d.numerator / d.denominator
    fig = go.Figure()
    for period, color, dash in (("previous", GRAY, "dot"), ("current", BLUE, "solid")):
        s = d[d.period == period].sort_values("day")
        if s.empty:
            continue
        fig.add_trace(go.Scatter(x=s.day, y=s.value, name=f"{period.title()} period", mode="lines+markers",
                                 line=dict(color=color, width=2, dash=dash), marker=dict(size=8),
                                 hovertemplate=("%{y:.2%}" if ratio else "%{y:,.0f}") + "<extra>" + period + "</extra>"))
    if baseline is not None:
        fig.add_hline(y=baseline, line=dict(color=GRAY, dash="dash", width=1),
                      annotation_text=f"previous-period level {baseline:.2%}", annotation_position="bottom right")
    fig.update_layout(title=title)
    if ratio:
        fig.update_yaxes(tickformat=".0%")
    return fig_style(fig)


def chart_waterfall(d: dict) -> go.Figure:
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=["absolute", "relative", "relative", "total"],
        x=["Previous<br>rate", "Traffic-mix<br>effect", "Within-segment<br>rate effect", "Current<br>rate"],
        y=[d["R0"] * 100, d["mix_effect"] * 100, d["rate_effect"] * 100, d["R1"] * 100],
        text=[f"{d['R0']:.2%}", pp(d["mix_effect"]), pp(d["rate_effect"]), f"{d['R1']:.2%}"],
        textposition="outside", connector=dict(line=dict(color=GRAY, width=1)),
        decreasing=dict(marker=dict(color=RED)), increasing=dict(marker=dict(color=BLUE)),
        totals=dict(marker=dict(color=GRAY)), hovertemplate="%{x}: %{text}<extra></extra>"))
    lo, hi = min(d["R0"], d["R1"]) * 100, max(d["R0"], d["R1"]) * 100
    fig.update_yaxes(range=[lo - 2.5, hi + 1.5], ticksuffix="%")
    fig.update_layout(title=f"Change decomposed · {' × '.join(d['keys'])}", showlegend=False)
    fig.update_xaxes(tickangle=0)
    return fig_style(fig, 360)


def chart_contrib(seg: pd.DataFrame, n: int = 8) -> go.Figure:
    s = seg.reindex(seg.contribution.abs().sort_values(ascending=False).index).head(n).iloc[::-1]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=s.segment, x=s.rate_effect * 100, name="Rate effect", orientation="h", marker_color=BLUE,
                         hovertemplate="%{y}<br>rate effect %{x:+.2f}pp<extra></extra>"))
    fig.add_trace(go.Bar(y=s.segment, x=s.mix_effect * 100, name="Mix effect", orientation="h", marker_color=ORANGE,
                         hovertemplate="%{y}<br>mix effect %{x:+.2f}pp<extra></extra>"))
    fig.update_layout(barmode="relative", title="Largest contributors (pp)", bargap=0.35)
    fig.update_xaxes(ticksuffix="pp", zeroline=True, zerolinecolor="rgba(128,128,128,.5)")
    return fig_style(fig, 360)


def seg_table(seg: pd.DataFrame) -> pd.DataFrame:
    cols = ["segment", "n0", "n1", "w0", "w1", "r0", "r1", "rate_change", "rate_effect", "mix_effect", "contribution", "p_value", "significant"]
    t = seg[[c for c in cols if c in seg]].copy()
    for c in ("w0", "w1", "r0", "r1"):
        if c in t:
            t[c] = t[c].map(pct)
    for c in ("rate_change", "rate_effect", "mix_effect", "contribution"):
        if c in t:
            t[c] = t[c].map(pp)
    if "p_value" in t:
        t["p_value"] = t["p_value"].map(lambda p: "<0.001" if p < 0.001 else f"{p:.3f}")
    return t.rename(columns={"n0": "attempts prev", "n1": "attempts cur", "w0": "share prev", "w1": "share cur",
                             "r0": "rate prev", "r1": "rate cur", "rate_change": "rate Δ"})


def render_analysis_tabs(res) -> None:
    a, T = res.analysis, res.tables
    ratio = a.get("kind") == "ratio"
    names = []
    if a.get("decomposition"):
        names.append("Root cause")
    if "trend" in T:
        names.append("Trend")
    if any(k.startswith("dim_") for k in T) or "breakdown" in T:
        names.append("Segments")
    if a.get("drilldown"):
        names.append("Drill-down")
    if a.get("reconciliation"):
        names.append("Reconciliation")
    names += ["Data quality", "Evidence & SQL", "Pipeline trace"]
    tabs = dict(zip(names, st.tabs(names)))

    if "Root cause" in tabs:
        with tabs["Root cause"]:
            d = a["decomposition"]
            c1, c2 = st.columns(2)
            c1.plotly_chart(chart_waterfall(d), use_container_width=True)
            c2.plotly_chart(chart_contrib(T["segments"]), use_container_width=True)
            k = st.columns(4)
            k[0].metric("Observed change", pp(d["delta"]))
            k[1].metric("Traffic-mix effect", pp(d["mix_effect"]))
            k[2].metric("Within-segment rate effect", pp(d["rate_effect"]))
            k[3].metric("Residual (must be ~0)", f"{d['residual']:.1e}")
            st.markdown("##### Counterfactual: what if the traffic mix had not changed?")
            cc = st.columns(3)
            cc[0].metric("Actual current rate", pct(d["R1"]))
            cc[1].metric("Current segment rates at previous mix", pct(d["counterfactual_rate"]),
                         pp(d["counterfactual_rate"] - d["R1"]) + " vs actual", delta_color="off")
            cc[2].metric("Interaction term", pp(d["interaction"]))
            st.caption(f"Under the counterfactual convention performance = {pp(d['cf_rate_effect'])} and mix = {pp(d['cf_mix_effect'])}. "
                       "The symmetric split shares the interaction term equally between the two, which is why it differs slightly.")
            sim = a.get("simpson") or {}
            if sim.get("detected"):
                st.error(f"**Simpson's paradox detected ({sim.get('level')} level).** {sim['message']}")
            else:
                st.info("Simpson's-paradox check: not detected - at least one sizeable segment deteriorated significantly.")
            st.markdown(f"**Segment table** - a segment can only be *significant* with ≥ "
                        f"{semantic()['root_cause']['min_segment_attempts']} attempts in both periods and p < 0.05")
            st.dataframe(seg_table(T["segments"]), use_container_width=True, hide_index=True)

    if "Trend" in tabs:
        with tabs["Trend"]:
            st.plotly_chart(chart_trend(T["trend"], f"Daily {a['metric_label']}", ratio), use_container_width=True)
            if a.get("trend_summary"):
                st.caption(a["trend_summary"])

    if "Segments" in tabs:
        with tabs["Segments"]:
            if "breakdown" in T:
                b = T["breakdown"]
                if ratio and "r1" in b:
                    s = b.sort_values("r1")
                    fig = go.Figure()
                    if "r0" in s:
                        fig.add_trace(go.Bar(x=s.segment, y=s.r0, name="Previous", marker_color=GRAY,
                                             hovertemplate="%{x}: %{y:.2%}<extra>previous</extra>"))
                    fig.add_trace(go.Bar(x=s.segment, y=s.r1, name="Current", marker_color=BLUE,
                                         hovertemplate="%{x}: %{y:.2%}<extra>current</extra>"))
                    fig.update_layout(barmode="group", title=f"{a['metric_label']} by {' x '.join(a.get('breakdown_dims', []))}", bargap=0.3)
                    fig.update_yaxes(tickformat=".0%", range=[max(0, s.r1.min() - 0.08), 1])
                    st.plotly_chart(fig_style(fig), use_container_width=True)
                    st.dataframe(seg_table(b), use_container_width=True, hide_index=True)
                else:
                    st.dataframe(b, use_container_width=True, hide_index=True)
            for dim in semantic()["root_cause"]["driver_dimensions"]:
                if f"dim_{dim}" in T and ratio:
                    v = a.get("dimension_views", {}).get(dim, {})
                    st.markdown(f"**By {dim}** - rate effect {pp(v.get('rate_effect'))}, mix effect {pp(v.get('mix_effect'))}")
                    st.dataframe(seg_table(T[f"dim_{dim}"]), use_container_width=True, hide_index=True)
            if a.get("grain"):
                st.caption(f"The mix/rate split depends on how segments are cut; the headline uses {' x '.join(a['grain'])}.")

    if "Drill-down" in tabs:
        with tabs["Drill-down"]:
            dd = a["drilldown"]
            st.markdown(f"Automatic drill-down into the strongest significant rate driver: **{dd['segment']}**")
            c1, c2 = st.columns(2)
            r = T["drill_reasons"].iloc[::-1]
            fig = go.Figure()
            fig.add_trace(go.Bar(y=r.decline_reason, x=r.previous, name="Previous", marker_color=GRAY, orientation="h",
                                 hovertemplate="%{y}: %{x:,} failures<extra>previous</extra>"))
            fig.add_trace(go.Bar(y=r.decline_reason, x=r.current, name="Current", marker_color=BLUE, orientation="h",
                                 hovertemplate="%{y}: %{x:,} failures<extra>current</extra>"))
            fig.update_layout(barmode="group", title=f"Failed attempts by decline reason · {dd['segment']}", bargap=0.25)
            c1.plotly_chart(fig_style(fig), use_container_width=True)
            c2.plotly_chart(chart_trend(T["drill_daily"], f"Daily success · {dd['segment']}", True, dd["baseline"]),
                            use_container_width=True)
            if dd.get("bad_days"):
                st.markdown(f"Days more than 3 standard errors below the previous-period level: **{', '.join(dd['bad_days'])}**")

    if "Reconciliation" in tabs:
        with tabs["Reconciliation"]:
            rc = a["reconciliation"]
            comp = pd.DataFrame(rc["components"])
            gap = comp.iloc[1:]
            fig = go.Figure(go.Bar(x=gap.component, y=gap.amount, marker_color=[ORANGE, BLUE, RED],
                                   hovertemplate="%{x}: INR %{y:,.2f}<extra></extra>"))
            fig.update_layout(title=f"Unsettled gap of INR {rc['gap_amount']:,.2f} explained")
            st.plotly_chart(fig_style(fig), use_container_width=True)
            comp["amount"] = comp["amount"].map(lambda x: f"{x:,.2f}")
            st.dataframe(comp, use_container_width=True, hide_index=True)
            st.caption("Identity: successful = settled gross + mismatch on settled + pending + missing. "
                       f"Holds: {rc['identity_holds']}")

    with tabs["Data quality"]:
        dq = res.dq or {}
        if dq.get("checks"):
            sev = {"ok": "OK", "info": "Info", "warning": "Warning"}
            t = pd.DataFrame(dq["checks"])
            t["severity"] = t["severity"].map(sev)
            st.dataframe(t[["check", "severity", "count", "detail", "handling", "query_id"]], use_container_width=True, hide_index=True)
        imp = dq.get("raw_vs_trusted")
        if imp:
            c = st.columns(3)
            c[0].metric("Raw data", pct(imp["raw_rate"]), f"n={imp['raw_denominator']:,}", delta_color="off")
            c[1].metric("Trusted view", pct(imp["trusted_rate"]), f"n={imp['trusted_denominator']:,}", delta_color="off")
            c[2].metric("Sources disagree by", f"{imp['difference_pp']:+.2f}pp")

    with tabs["Evidence & SQL"]:
        rq = res.resolved
        st.markdown(f"**Metric definition:** {rq.metric_spec['description']}")
        st.markdown(f"**Excluded:** {', '.join(rq.metric_spec.get('excluded', [])) or '—'}")
        st.markdown(f"**Datasets:** {', '.join(sorted({t for q in res.queries for t in q.tables}))} · "
                    f"**Period:** {rq.current.pretty()} vs {rq.previous.pretty() if rq.previous else '—'} · "
                    f"**Filters:** {rq.filters or 'none'} · **Role:** {labels[res.role]}")
        st.markdown("**Facts and the queries behind them**")
        st.dataframe(pd.DataFrame([{"fact": f.id, "statement": f.text, "queries": ", ".join(f.query_ids)} for f in res.facts]),
                     use_container_width=True, hide_index=True)
        for q in res.queries:
            with st.expander(f"{q.id} · {q.purpose} · {q.status} · {q.rows} rows · {q.elapsed_ms} ms{' · cache hit' if q.cache_hit else ''}"):
                st.code(q.executed_sql or q.sql, language="sql")
                if q.executed_sql and q.executed_sql != q.sql:
                    st.caption("Row-level scope rewrite applied for your role. Compiled SQL before the rewrite:")
                    st.code(q.sql, language="sql")
                st.dataframe(pd.DataFrame(q.checks), use_container_width=True, hide_index=True)

    with tabs["Pipeline trace"]:
        st.dataframe(pd.DataFrame([t.__dict__ for t in res.trace]), use_container_width=True, hide_index=True)
        st.caption("Every step that ran, the file::function that ran it, and how long it took (ms).")


# ----------------------------------------------------------------------------- Ask tab
with tab_ask:
    st.markdown("<div class='pl-hero'><h1>Ask a question about payment performance</h1>"
                "<p>Every answer shows the SQL, the data checks and the assumptions behind its numbers.</p></div>",
                unsafe_allow_html=True)
    ask_slot = st.container()   # placed first on the page but filled later, so clicking an example can fill in the question box
    st.caption("Or start from an example")
    cols = st.columns(4)
    for i, (label, ex) in enumerate(EXAMPLES.items()):
        if cols[i % 4].button(label, key=f"ex{i}", use_container_width=True, help=ex):
            st.session_state["question"] = ex
            st.session_state["run"] = True
    with ask_slot, st.form("ask"):
        q = st.text_input("Question", key="question", label_visibility="collapsed",
                          placeholder="e.g. Why did payment success rate fall last week?")
        if st.form_submit_button("Analyse", type="primary"):
            st.session_state["run"] = True
    if st.session_state.get("run") and st.session_state.get("question"):
        with st.spinner("Understanding the question, compiling and validating SQL, analysing…"):
            res = pl.run(st.session_state["question"], role, use_llm=use_llm)
        render_status(res)
        if res.status == "ANSWERED":
            render_understanding(res)
            render_kpis(res)
            render_dq_banner(res)
            render_narrative(res)
            render_analysis_tabs(res)
        elif res.trace:
            with st.expander("What ran before stopping"):
                st.dataframe(pd.DataFrame([t.__dict__ for t in res.trace]), use_container_width=True, hide_index=True)

# ----------------------------------------------------------------------------- SQL Explorer
with tab_sql:
    st.markdown("### SQL Explorer (guarded)")
    st.caption(f"Every query is parsed and validated, scoped to your role, run read-only with a "
               f"{limits()['query_timeout_seconds']}s timeout and {limits()['max_rows']:,}-row limit, and logged.")
    presets = {
        "Success rate by bank (safe)": "SELECT b.bank_name, COUNT(*) AS attempts,\n  AVG(CASE WHEN t.status = 'SUCCESS' THEN 1.0 ELSE 0.0 END) AS success_rate\nFROM transactions t JOIN banks b ON t.bank_id = b.bank_id\nWHERE t.status IN ('SUCCESS','FAILED') AND t.created_at >= TIMESTAMP '2026-11-09'\nGROUP BY 1 ORDER BY 3",
        "Merchant bank accounts (restricted)": "SELECT merchant_id, settlement_account FROM merchants",
        "Drop a table (unsafe)": "DROP TABLE transactions",
        "Read a local file (unsafe)": "SELECT * FROM read_csv('C:/Users/secrets.csv')",
        "Cartesian join (expensive)": "SELECT COUNT(*) AS n FROM transactions t, transactions_raw r",
    }
    pc = st.columns(len(presets))
    for i, (k, v) in enumerate(presets.items()):
        if pc[i].button(k, key=f"p{i}", use_container_width=True):
            st.session_state["sql"] = v
    mode = st.radio("Input", ["SQL", "Natural language → SQL (OpenAI)"], horizontal=True,
                    disabled=not llm_configured(), index=0)
    if "sql" not in st.session_state:
        st.session_state["sql"] = list(presets.values())[0]
    text = st.text_area("Query", key="sql", height=150)
    if st.button("Validate & run", type="primary"):
        out = pl.explore(text, role, is_sql=(mode == "SQL"), use_llm=use_llm)
        if out.get("generated"):
            st.markdown(f"**Generated SQL** - {out['generated']['explanation']}")
            st.code(out["generated"]["sql"], language="sql")
        rec = out.get("record")
        if out["status"] == "OK":
            st.success(f"Allowed · {out['message']} · {rec.elapsed_ms} ms{' · cache hit' if rec.cache_hit else ''}")
            st.dataframe(out["df"], use_container_width=True, hide_index=True)
        else:
            st.error(f"**{STATUS.get(out['status'], out['status'])}.** {out['message']}")
        if rec:
            st.markdown("**Guard checks**")
            st.dataframe(pd.DataFrame(rec.checks), use_container_width=True, hide_index=True)
            if rec.executed_sql and rec.executed_sql != rec.sql:
                st.markdown("**Executed after the row-scope rewrite for your role**")
                st.code(rec.executed_sql, language="sql")

# ----------------------------------------------------------------------------- Audit & definitions
with tab_audit:
    st.markdown("### Audit log (most recent first)")
    ev = audit.recent(300)
    if ev:
        df = pd.DataFrame(ev)
        show = [c for c in ["ts", "role", "mode", "decision", "purpose", "question", "reason", "rows", "elapsed_ms", "cache_hit"] if c in df]
        st.dataframe(df[show], use_container_width=True, hide_index=True)
    else:
        st.info("No queries logged yet.")

with tab_def:
    sem = semantic()
    st.markdown("### Metric definitions (semantic layer - `config/metrics.yaml`)")
    for name, m in sem["metrics"].items():
        st.markdown(f"**{m['label']}** (`{name}`, {m['kind']}, grain: {m['grain']})  \n{m['description']}")
        if m["kind"] == "ratio":
            st.markdown(f"<span class='pl-small'>Numerator: {m['numerator']} · Denominator: {m['denominator']} · "
                        f"Excluded: {', '.join(m.get('excluded', []))}</span>", unsafe_allow_html=True)
    st.markdown("### Roles (simulated RBAC - `config/policies.yaml`)")
    st.dataframe(pd.DataFrame([{"role": k, "label": v["label"], "restricted columns": ", ".join(v["restricted_columns"]) or "none",
                                "row scope": (f"{v['row_scope']['column']} = {v['row_scope']['value']}" if v["row_scope"] else "all rows")}
                               for k, v in policies()["roles"].items()]), use_container_width=True, hide_index=True)
    st.markdown("### Query budget")
    st.json(limits())
