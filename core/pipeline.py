"""Runs a question end to end: intent, access check, SQL, analysis, data quality and narrative."""
from __future__ import annotations

import math
import time
from contextlib import contextmanager
from datetime import date

import pandas as pd

from ai.intent_parser import parse_question
from ai.llm_client import LLMUnavailable, structured_call
from ai.narrator import narrate
from analytics import data_quality, insights
from analytics.decomposition import additive_breakdown, decompose, segment_table, simpson_check, top_drivers
from analytics.reconciliation import reconcile
from analytics.stats import two_proportion_z, wilson_ci
from core.config import PROMPT_DIR, limits, semantic
from core.models import AnalysisResult, Period, ResolvedQuery, TraceStep
from core.time_resolver import TimeResolutionError, requested_days, resolve_periods
from security import audit
from security.policy import check_intent, role_config
from sqlengine.compiler import compile_decline_reasons, compile_distinct_values, compile_metric
from sqlengine.executor import Executor
from sqlengine.service import QueryBlocked, QueryError, QueryService
from pydantic import BaseModel

CAPABILITIES = ("I can analyse payment success rate (attempt level), order conversion rate (net of retries), "
                "successful GMV and transaction counts - as a summary, trend, breakdown or root-cause analysis - "
                "by bank, payment method, merchant category, region, merchant ID or decline reason, and reconcile "
                "transactions against settlements.")


class ExploreSQL(BaseModel):
    sql: str
    explanation: str


class PaymentLens:
    def __init__(self, executor: Executor | None = None):
        self.ex = executor or Executor()
        self.as_of = self.ex.data_as_of
        self._catalog: dict[str, list[str]] | None = None

    # ------------------------------------------------------------------ helpers
    def catalog(self) -> dict[str, list[str]]:
        if self._catalog is None:
            svc = QueryService(self.ex, "admin", mode="system", question="catalog")
            q = compile_distinct_values()
            df, _ = svc.run(q.sql, q.purpose)
            self._catalog = {d: sorted(g["value"].astype(str).unique().tolist()) for d, g in df.groupby("dimension")}
        return self._catalog

    @contextmanager
    def _step(self, res: AnalysisResult, step: str, component: str):
        t0 = time.perf_counter()
        holder = {"detail": ""}
        try:
            yield holder
        finally:
            res.trace.append(TraceStep(step, component, holder["detail"], round((time.perf_counter() - t0) * 1000, 1)))

    def _canonical_filters(self, intent) -> tuple[dict[str, list[str]], list[str]]:
        cat = self.catalog()
        out: dict[str, list[str]] = {}
        unknown: list[str] = []
        for f in intent.filters:
            valid = cat.get(f.dimension, [])
            for v in f.values:
                match = next((x for x in valid if x.lower() == v.lower()), None) or \
                        next((x for x in valid if x.lower().startswith(v.lower()) and len(v) >= 3), None)
                if match:
                    out.setdefault(f.dimension, [])
                    if match not in out[f.dimension]:
                        out[f.dimension].append(match)
                else:
                    unknown.append(f"{f.dimension}='{v}' (valid: {', '.join(valid[:12])})")
        return out, unknown

    @staticmethod
    def _overall(df: pd.DataFrame, kind: str) -> dict:
        out: dict = {}
        for label in ("previous", "current"):
            d = df[df.period == label]
            if d.empty:
                continue
            if kind == "ratio":
                s, n = int(d.numerator.sum()), int(d.denominator.sum())
                out[label] = {"value": s / n if n else float("nan"), "num": s, "den": n, "ci": wilson_ci(s, n)}
            else:
                out[label] = {"value": float(d.value.sum()), "num": None, "den": None, "ci": None}
        if "previous" in out and "current" in out:
            out["delta"] = out["current"]["value"] - out["previous"]["value"]
            if kind == "ratio":
                out["p_value"] = two_proportion_z(out["previous"]["num"], out["previous"]["den"],
                                                  out["current"]["num"], out["current"]["den"])[1]
        return out

    # ------------------------------------------------------------------ main entry
    def run(self, question: str, role: str, use_llm: bool = True) -> AnalysisResult:
        res = AnalysisResult(question=question, role=role)
        svc = QueryService(self.ex, role, mode="guided", question=question)
        try:
            self._run(res, svc, question, role, use_llm)
        except QueryBlocked as e:
            res.status, res.message = "BLOCKED", f"A generated query was blocked by the SQL guard: {e}"
        except QueryError as e:
            res.status, res.message = "ERROR", f"Query failed: {e}"
        except Exception as e:  # never crash the app; show what went wrong
            res.status, res.message = "ERROR", f"Unexpected error: {type(e).__name__}: {e}"
        finally:
            res.queries = svc.records
        return res

    def _run(self, res: AnalysisResult, svc: QueryService, question: str, role: str, use_llm: bool) -> None:
        sem, lim = semantic(), limits()

        with self._step(res, "Check data freshness", "analytics/data_quality.py::freshness") as st:
            fresh = data_quality.freshness(svc, self.as_of)
            st["detail"] = f"last day {fresh['last_day']} partial={fresh['is_partial']}; last complete {fresh['last_complete_day']}"

        with self._step(res, "Understand question", "ai/intent_parser.py::parse_question") as st:
            intent, parser, notes, meta = parse_question(
                question, self.catalog(), as_of=self.as_of, data_start=str(fresh["first_day"]),
                last_complete=str(fresh["last_complete_day"]), use_llm=use_llm)
            res.intent, res.parser_used, res.parser_notes = intent, parser, notes
            res.analysis["llm_meta"] = meta
            st["detail"] = f"parser={parser}; metric={intent.metric}; analysis={intent.analysis_type}; dims={intent.dimensions}"

        # check access first: if the question asks for restricted data, deny it right away,
        # even if the question is also unsupported, so the user sees 'access denied'
        pre = check_intent(intent, role, {})
        if pre.status == "DENIED":
            res.policy = pre.__dict__
            res.trace.append(TraceStep("Check access policy", "security/policy.py::check_intent", f"DENIED {pre.reasons}", 0.0))
            res.status, res.message = "DENIED", " ".join(pre.reasons)
            audit.log_event(role=role, mode="guided", question=question, decision="DENIED", reason=res.message)
            return

        if not intent.is_supported:
            res.status = "UNSUPPORTED"
            res.message = f"{intent.unsupported_reason} {CAPABILITIES}"
            audit.log_event(role=role, mode="guided", question=question, decision="UNSUPPORTED", reason=intent.unsupported_reason)
            return

        with self._step(res, "Validate filter values", "core/pipeline.py::_canonical_filters") as st:
            filters, unknown = self._canonical_filters(intent)
            st["detail"] = f"filters={filters} unknown={unknown}"
        if unknown:
            res.status = "UNSUPPORTED"
            res.message = "Unknown filter value(s): " + "; ".join(unknown)
            return

        with self._step(res, "Check access policy", "security/policy.py::check_intent") as st:
            decision = check_intent(intent, role, filters)
            res.policy = decision.__dict__
            st["detail"] = f"{decision.status} {decision.reasons or decision.notices}"
        if decision.status == "DENIED":
            res.status = "DENIED"
            res.message = " ".join(decision.reasons)
            audit.log_event(role=role, mode="guided", question=question, decision="DENIED", reason=res.message)
            return
        if intent.requested_attributes:
            res.status = "UNSUPPORTED"
            res.message = ("Listing record-level merchant attributes is not part of guided analysis. "
                           "Your role may use the SQL Explorer for record-level queries.")
            return
        filters = decision.scoped_filters or filters

        asked = [d for d in (requested_days(intent.current_period),
                             requested_days(intent.comparison_period) if intent.comparison_period else None) if d]
        if asked and max(asked) > lim["max_range_days"]:
            res.status = "BLOCKED"
            res.message = (f"Query blocked: the requested period ({max(asked)} days) exceeds the "
                           f"{lim['max_range_days']}-day interactive analytics limit. Please choose a shorter period.")
            audit.log_event(role=role, mode="guided", question=question, decision="BLOCKED", reason=res.message)
            return

        with self._step(res, "Resolve time periods", "core/time_resolver.py::resolve_periods") as st:
            assumptions: list[str] = []
            try:
                current, previous = resolve_periods(intent, fresh["last_complete_day"], fresh["first_day"], assumptions)
            except TimeResolutionError as e:
                res.status, res.message = "UNSUPPORTED", f"Time period problem: {e}"
                st["detail"] = str(e)
                return
            st["detail"] = f"current={current.pretty()} previous={previous.pretty() if previous else None}"
        if fresh["is_partial"]:
            assumptions.append(f"{fresh['last_day']:%d %b} is partially loaded and excluded from relative periods.")

        # Root cause already checks every dimension by itself. If the AI lists many dimensions for a "why"
        # question, ignore that list and use the default split instead of blocking the query.
        # If the user named one or two dimensions, use those for the split.
        if intent.analysis_type == "root_cause" and len([d for d in intent.dimensions if d != "day"]) > 2:
            assumptions.append(f"Root-cause analysis checks bank, payment method, merchant category and region automatically; "
                               f"the parsed dimension list {intent.dimensions} was not used as the decomposition grain.")
            intent.dimensions = []

        with self._step(res, "Apply query budget", "core/pipeline.py::_run (limits)") as st:
            too_long = [p for p in (current, previous) if p and p.days > lim["max_range_days"]]
            user_dims = [d for d in intent.dimensions if d != "day"]
            st["detail"] = f"days={current.days}, dims={len(user_dims)}"
        if too_long:
            res.status = "BLOCKED"
            res.message = (f"Query blocked: the requested period ({too_long[0].days} days) exceeds the "
                           f"{lim['max_range_days']}-day interactive analytics limit.")
            audit.log_event(role=role, mode="guided", question=question, decision="BLOCKED", reason=res.message)
            return
        if len(user_dims) > lim["max_dimensions"]:
            res.status = "BLOCKED"
            res.message = f"Query blocked: at most {lim['max_dimensions']} breakdown dimensions are allowed."
            return

        spec = sem["metrics"][intent.metric]
        source = "transactions_raw" if intent.data_source == "raw" else "transactions"
        if source == "transactions_raw":
            assumptions.append("Using RAW data as requested: duplicates and invalid rows are NOT removed.")
        res.resolved = ResolvedQuery(metric=intent.metric, metric_spec=spec, analysis_type=intent.analysis_type,
                                     current=current, previous=previous, dimensions=intent.dimensions,
                                     filters=filters, source_table=source, role=role,
                                     assumptions=assumptions, notices=decision.notices)
        res.analysis.update({"metric_label": spec["label"], "kind": spec["kind"]})

        handler = {"root_cause": self._root_cause, "trend": self._trend, "breakdown": self._breakdown,
                   "summary": self._summary, "reconciliation": self._reconciliation}[intent.analysis_type]
        with self._step(res, f"Run analysis: {intent.analysis_type}", f"core/pipeline.py::{handler.__name__}") as st:
            handler(res, svc)
            st["detail"] = f"{len(svc.records)} queries so far"

        with self._step(res, "Data-quality gate", "analytics/data_quality.py::run_checks") as st:
            periods = [p for p in (current, previous) if p]
            res.dq = data_quality.run_checks(svc, periods, self.as_of, intent.metric, filters, fresh)
            st["detail"] = f"{res.dq['warnings']} warning(s)"

        with self._step(res, "Build facts", "analytics/insights.py::build_facts") as st:
            facts, refs = insights.build_facts(res)
            res.facts = facts
            st["detail"] = f"{len(facts)} facts"
        with self._step(res, "Write narrative", "ai/narrator.py::narrate") as st:
            draft = insights.template_narrative(res, facts, refs)
            res.narrative, n_notes = narrate(facts, draft, use_llm)
            res.parser_notes += n_notes
            st["detail"] = f"generated_by={res.narrative.generated_by}; grounding={res.narrative.grounding.get('passed')}"
        with self._step(res, "Score confidence", "analytics/insights.py::confidence") as st:
            res.confidence = insights.confidence(res)
            st["detail"] = f"{res.confidence['level']} ({res.confidence['score']})"

    # ------------------------------------------------------------------ analysis handlers
    def _periods(self, rq: ResolvedQuery) -> list[Period]:
        return [p for p in (rq.current, rq.previous) if p]

    def _summary(self, res: AnalysisResult, svc: QueryService) -> None:
        rq = res.resolved
        q = compile_metric(rq.metric, purpose=f"{rq.metric_spec['label']} overall", source=rq.source_table,
                           periods=self._periods(rq), dims=[], filters=rq.filters)
        df, rec = svc.run(q.sql, q.purpose)
        res.analysis.update({"main_query_id": rec.id, "overall": self._overall(df, rq.metric_spec["kind"])})
        res.tables["overall"] = df

    def _trend(self, res: AnalysisResult, svc: QueryService) -> None:
        rq = res.resolved
        dims = ["day"] + [d for d in rq.dimensions if d != "day"][:1]
        q = compile_metric(rq.metric, purpose=f"{rq.metric_spec['label']} by day", source=rq.source_table,
                           periods=self._periods(rq), dims=dims, filters=rq.filters)
        df, rec = svc.run(q.sql, q.purpose)
        kind = rq.metric_spec["kind"]
        if kind == "ratio":
            df["value"] = df.numerator / df.denominator
        res.tables["trend"] = df
        res.analysis.update({"main_query_id": rec.id, "trend_query_id": rec.id, "overall": self._overall(df, kind)})
        cur = df[df.period == "current"].groupby("day").agg(
            **({"num": ("numerator", "sum"), "den": ("denominator", "sum")} if kind == "ratio" else {"v": ("value", "sum")}))
        cur["v"] = cur.num / cur.den if kind == "ratio" else cur["v"]
        if len(cur):
            lo, hi = cur.v.idxmin(), cur.v.idxmax()
            fmt = insights.pct if kind == "ratio" else (lambda x: f"{x:,.2f}")
            res.analysis["trend_summary"] = (f"Daily {rq.metric_spec['label']} in {rq.current.pretty()} ranged from "
                                             f"{fmt(cur.v.min())} on {pd.Timestamp(lo):%d %b} to {fmt(cur.v.max())} on "
                                             f"{pd.Timestamp(hi):%d %b}.")

    def _breakdown(self, res: AnalysisResult, svc: QueryService) -> None:
        rq = res.resolved
        dims = [d for d in rq.dimensions if d != "day"] or ["bank"]
        kind = rq.metric_spec["kind"]
        q = compile_metric(rq.metric, purpose=f"{rq.metric_spec['label']} by {', '.join(dims)}", source=rq.source_table,
                           periods=self._periods(rq), dims=dims, filters=rq.filters)
        df, rec = svc.run(q.sql, q.purpose)
        res.analysis.update({"main_query_id": rec.id, "overall": self._overall(df, kind), "breakdown_dims": dims})
        min_n = semantic()["root_cause"]["min_segment_attempts"]
        if kind == "ratio" and rq.previous:
            d = decompose(segment_table(df, dims), dims, min_n=min_n)
            table = d.segments
        elif kind == "ratio":
            table = df.groupby(dims)[["numerator", "denominator"]].sum().reset_index()
            table["r1"] = table.numerator / table.denominator
            table["n1"] = table.denominator
            table["segment"] = table[dims].astype(str).agg(" | ".join, axis=1)
        else:
            table = additive_breakdown(df, dims)
            table["segment"] = table[dims].astype(str).agg(" | ".join, axis=1)
        res.tables["breakdown"] = table
        if kind == "ratio":
            big = table[table.n1 >= min_n].sort_values("r1")
            if len(big):
                lo, hi = big.iloc[0], big.iloc[-1]
                res.analysis["breakdown_top"] = [
                    f"By {' x '.join(dims)} ({rq.current.pretty()}): lowest {rq.metric_spec['label']} is {lo.segment} at "
                    f"{insights.pct(lo.r1)} (n={int(lo.n1):,}); highest is {hi.segment} at {insights.pct(hi.r1)} (n={int(hi.n1):,})."]

    def _reconciliation(self, res: AnalysisResult, svc: QueryService) -> None:
        rq = res.resolved
        rc = reconcile(svc, rq.current)
        res.analysis.update({"reconciliation": rc, "main_query_id": rc["query_id"]})
        res.tables["reconciliation"] = pd.DataFrame(rc["components"])

    def _root_cause(self, res: AnalysisResult, svc: QueryService) -> None:
        rq, rc_cfg = res.resolved, semantic()["root_cause"]
        kind = rq.metric_spec["kind"]
        # a dimension that a filter (or the user's role) fixes to one value cannot explain the change
        grain = [d for d in rq.dimensions if d != "day" and len(rq.filters.get(d, [])) != 1] \
            or list(rc_cfg["decomposition_grain"])
        dims = list(dict.fromkeys(list(rc_cfg["driver_dimensions"]) + grain))
        periods = self._periods(rq)
        q = compile_metric(rq.metric, purpose=f"Root cause: {rq.metric_spec['label']} by {', '.join(dims)} for both periods",
                           source=rq.source_table, periods=periods, dims=dims, filters=rq.filters)
        df, rec = svc.run(q.sql, q.purpose)
        res.tables["root_cause_base"] = df
        res.analysis.update({"main_query_id": rec.id, "overall": self._overall(df, kind), "grain": grain})

        qt = compile_metric(rq.metric, purpose=f"Trend: {rq.metric_spec['label']} by day", source=rq.source_table,
                            periods=periods, dims=["day"], filters=rq.filters)
        tdf, trec = svc.run(qt.sql, qt.purpose)
        if kind == "ratio":
            tdf["value"] = tdf.numerator / tdf.denominator
        res.tables["trend"] = tdf
        res.analysis["trend_query_id"] = trec.id

        if kind != "ratio":
            res.tables["segments"] = additive_breakdown(df, grain)
            for dim in rc_cfg["driver_dimensions"]:
                res.tables[f"dim_{dim}"] = additive_breakdown(df, [dim])
            return

        min_n, alpha = rc_cfg["min_segment_attempts"], rc_cfg["significance_alpha"]
        d = decompose(segment_table(df, grain), grain, min_n=min_n, alpha=alpha)
        res.tables["segments"] = d.segments
        res.analysis["decomposition"] = {
            "keys": grain, "R0": d.R0, "R1": d.R1, "delta": d.delta, "rate_effect": d.rate_effect,
            "mix_effect": d.mix_effect, "interaction": d.interaction, "counterfactual_rate": d.counterfactual_rate,
            "cf_rate_effect": d.cf_rate_effect, "cf_mix_effect": d.cf_mix_effect, "residual": d.residual,
            "reconciles": d.reconciles}
        drv = top_drivers(d)
        cols = ["segment", "w0", "w1", "r0", "r1", "rate_change", "share_change", "rate_effect", "mix_effect",
                "contribution", "p_value", "significant", "n0", "n1"]
        res.analysis["drivers"] = {k: v[cols].to_dict("records") for k, v in drv.items()}

        views, simpson = {}, simpson_check(d, res.analysis["overall"].get("p_value", 1.0), alpha)
        simpson["level"] = " x ".join(grain)
        for dim in rc_cfg["driver_dimensions"]:
            dv = decompose(segment_table(df, [dim]), [dim], min_n=min_n, alpha=alpha)
            res.tables[f"dim_{dim}"] = dv.segments
            seg = dv.segments
            top_mix = seg.sort_values("mix_effect", ascending=d.delta < 0).iloc[0]
            top_rate = seg.sort_values("rate_effect", ascending=d.delta < 0).iloc[0]
            views[dim] = {"rate_effect": dv.rate_effect, "mix_effect": dv.mix_effect, "rbar": (dv.R0 + dv.R1) / 2,
                          "top_mix": top_mix[cols].to_dict(), "top_rate": top_rate[cols].to_dict()}
            if not simpson.get("detected"):
                s2 = simpson_check(dv, res.analysis["overall"].get("p_value", 1.0), alpha)
                if s2.get("detected"):
                    simpson = {**s2, "level": dim}
        res.analysis["dimension_views"] = views
        res.analysis["simpson"] = simpson

        # drill into the segment whose rate changed the most in the same direction as the total (and is significant)
        cand = [r for r in res.analysis["drivers"]["rate"]
                if r["significant"] and math.copysign(1, r["rate_change"]) == math.copysign(1, d.delta)]
        if not cand:
            return
        top = cand[0]
        seg_row = d.segments[d.segments.segment == top["segment"]].iloc[0]
        dfilters = {k: list(v) for k, v in rq.filters.items()}
        for k in grain:
            dfilters[k] = [str(seg_row[k])]
        qr = compile_decline_reasons(source=rq.source_table, periods=periods, filters=dfilters)
        rdf, rrec = svc.run(qr.sql, qr.purpose)
        piv = rdf.pivot_table(index="decline_reason", columns="period", values="failures", aggfunc="sum").fillna(0)
        for c in ("previous", "current"):
            if c not in piv:
                piv[c] = 0
        piv["share_prev"] = piv["previous"] / max(piv["previous"].sum(), 1)
        piv["share_cur"] = piv["current"] / max(piv["current"].sum(), 1)
        piv["increase"] = piv["current"] - piv["previous"]
        piv = piv.sort_values("increase", ascending=False).reset_index()
        res.tables["drill_reasons"] = piv
        qd = compile_metric(rq.metric, purpose=f"Drill-down: daily {rq.metric_spec['label']} for {top['segment']}",
                            source=rq.source_table, periods=periods, dims=["day"], filters=dfilters)
        ddf, drec = svc.run(qd.sql, qd.purpose)
        ddf["value"] = ddf.numerator / ddf.denominator
        res.tables["drill_daily"] = ddf
        r0 = float(seg_row["r0"])
        cur_days = ddf[ddf.period == "current"]
        bad = [pd.Timestamp(r.day).strftime("%d %b") for r in cur_days.itertuples()
               if r.value < r0 - 3 * math.sqrt(r0 * (1 - r0) / max(r.denominator, 1))]
        tr = piv.iloc[0]
        res.analysis["drilldown"] = {
            "segment": top["segment"], "filters": dfilters, "top_reason": str(tr["decline_reason"]),
            "reason_prev": int(tr["previous"]), "reason_cur": int(tr["current"]),
            "reason_share_prev": float(tr["share_prev"]), "reason_share_cur": float(tr["share_cur"]),
            "baseline": r0, "bad_days": bad, "reason_query_id": rrec.id, "daily_query_id": drec.id}

    # ------------------------------------------------------------------ SQL explorer
    def explore(self, text: str, role: str, is_sql: bool, use_llm: bool = True) -> dict:
        svc = QueryService(self.ex, role, mode="explore", question=text)
        out: dict = {"input": text, "generated": None}
        if not role_config(role).get("explore_mode"):
            return {**out, "status": "DENIED", "message": "Your role cannot use the SQL Explorer."}
        sql = text
        if not is_sql:
            try:
                schema = "\n".join(f"- {t}({', '.join(c)})" for t, c in self.ex.schema.items())
                fresh = data_quality.freshness(svc, self.as_of)
                system = ((PROMPT_DIR / "explore_sql_system.md").read_text(encoding="utf-8")
                          .replace("{{SCHEMA}}", schema).replace("{{DATA_START}}", str(fresh["first_day"]))
                          .replace("{{LAST_COMPLETE}}", str(fresh["last_complete_day"])))
                gen, meta = structured_call(system, text, ExploreSQL)
                sql = gen.sql
                out["generated"] = {"sql": gen.sql, "explanation": gen.explanation, "llm": meta}
            except LLMUnavailable as e:
                return {**out, "status": "ERROR", "message": f"AI SQL generation unavailable ({e}). Type SQL directly instead.",
                        "records": svc.records}
        max_rows = int(limits()["max_rows"])
        try:
            df, rec = svc.run(sql, "SQL Explorer query", max_rows=max_rows)
        except QueryBlocked as e:
            return {**out, "status": "BLOCKED", "message": str(e), "record": e.record, "records": svc.records}
        except QueryError as e:
            return {**out, "status": "ERROR", "message": str(e), "record": e.record, "records": svc.records}
        truncated = len(df) > max_rows
        return {**out, "status": "OK", "df": df.head(max_rows), "truncated": truncated, "record": rec,
                "records": svc.records, "message": f"{min(len(df), max_rows)} rows" + (" (truncated)" if truncated else "")}
