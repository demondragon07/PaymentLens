"""Builds the code architecture guide PDF from the code and recorded outputs."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs"))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

from pdfkit import (Book, CONTENT_W, EVID, callers, er_diagram, esc, ev, pct, pipeline_diagram, pp,  # noqa: E402
                    project_imports, sequence_diagram, signature_list, source_of, tag)

OUT = ROOT / "docs" / "PaymentLens_Complete_Code_Architecture_Guide.pdf"

M, SIM, RAW, DEN, REG, REC, UNS, BUD, BRK, ORD, ALT = (ev(k) for k in (
    "main", "simpson", "raw", "denied", "regional", "recon", "unsupported", "budget", "breakdown", "order", "alternative"))
GT = json.loads((ROOT / "data" / "ground_truth.json").read_text(encoding="utf-8"))
EVAL = json.loads((ROOT / "reports" / "eval_report_rules.json").read_text(encoding="utf-8"))
PYTEST = (EVID / "pytest_output.txt").read_text(encoding="utf-8", errors="ignore")
N_TESTS = int(re.search(r"(\d+) passed", PYTEST).group(1))
EVAL_LLM = json.loads((ROOT / "reports" / "eval_report_llm.json").read_text(encoding="utf-8"))
MLLM = ev("main_llm")
LLM_MODEL = MLLM.get("model", "configured OpenAI model")
A, D, OV = M["analysis"], M["analysis"]["decomposition"], M["analysis"]["overall"]
DD, BV = A["drilldown"], A["bank_view"]["top_mix"]
NU = A["drivers"]["rate"][0]
Q = {q["id"]: q for q in M["queries"]}

FILES = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.rglob("*.py")
               if not any(x in p.parts for x in (".venv", "__pycache__", "docs")))
FILES += [f for f in ("docs/pdfkit.py", "docs/build_pdf1.py", "docs/build_pdf2.py") if (ROOT / f).exists()]

PURPOSE = {
    "app.py": ("Streamlit user interface: question box, role switcher, answer cards, charts, evidence, SQL Explorer, audit log.", "implemented"),
    "core/config.py": ("Paths, constants (allowed tables, statuses), YAML loaders and lazily-read OpenAI settings.", "implemented"),
    "core/models.py": ("Data contracts: AnalysisIntent (Pydantic, LLM-facing), Period, ResolvedQuery, QueryRecord, Fact, Narrative, AnalysisResult.", "implemented"),
    "core/time_resolver.py": ("Turns relative time words into concrete date ranges using the last COMPLETE day; records assumptions.", "implemented"),
    "core/pipeline.py": ("Orchestrator. Runs every step in order, records a timed trace, and implements the five analysis handlers and the SQL Explorer.", "implemented"),
    "ai/llm_client.py": ("OpenAI Responses API wrapper with Structured Outputs; converts every failure into LLMUnavailable.", "implemented"),
    "ai/intent_parser.py": ("Question -> AnalysisIntent. LLM first, rule-based fallback; always merges rule-detected sensitive attributes.", "implemented"),
    "ai/rule_parser.py": ("Offline deterministic parser (keywords + date regexes) producing the same AnalysisIntent schema.", "implemented"),
    "ai/narrator.py": ("Optional LLM rewrite of the narrative, guarded by the number-grounding check; template fallback.", "implemented"),
    "sqlengine/compiler.py": ("Deterministic SQL compiler: metric/dimension names from YAML -> SQL text.", "implemented"),
    "sqlengine/guard.py": ("AST-based SQL safety validator (sqlglot) with a recorded pass/fail per check.", "implemented"),
    "sqlengine/executor.py": ("Read-only DuckDB connection, external access disabled, timeout via interrupt, result cache.", "implemented"),
    "sqlengine/service.py": ("The only path to the database: guard -> row-scope rewrite -> execute -> audit -> QueryRecord.", "implemented"),
    "analytics/stats.py": ("Wilson confidence interval and two-proportion z-test.", "implemented"),
    "analytics/decomposition.py": ("Mix vs rate decomposition, counterfactual, driver ranking, Simpson check, additive breakdown.", "implemented"),
    "analytics/data_quality.py": ("Freshness, duplicates, missing/orphan bank ids, invalid statuses, future timestamps, raw-vs-trusted impact.", "implemented"),
    "analytics/reconciliation.py": ("Successful transactions vs settlements with an exact identity check.", "implemented"),
    "analytics/insights.py": ("Facts with query ids, rule-based hypotheses and recommendations, confidence score.", "implemented"),
    "security/policy.py": ("Simulated RBAC: intent-level denial, restricted columns, row-scope SQL rewriting.", "mocked"),
    "security/audit.py": ("Append-only JSON-lines audit log of every query decision.", "implemented"),
    "data/generate_data.py": ("Synthetic data with planted scenarios and anomalies; independent pandas ground truth.", "mocked"),
    "scripts/run_eval.py": ("Known-answer evaluation (20 questions) scored against ground truth.", "implemented"),
    "scripts/capture_evidence.py": ("Runs demo questions and stores real outputs + charts used by these PDFs.", "implemented"),
    "tests/conftest.py": ("Pytest fixtures: shared pipeline, ground truth, LLM disabled.", "implemented"),
    "tests/test_math.py": ("Hand-checkable decomposition, counterfactual, Simpson, Wilson and z-test tests.", "implemented"),
    "tests/test_sql_guard.py": ("Malicious SQL, restricted columns, row-scope rewrite, read-only engine tests.", "implemented"),
    "tests/test_ground_truth.py": ("End-to-end answers vs data/ground_truth.json.", "implemented"),
    "tests/test_ai_layer.py": ("LLM fallback, sensitive-attribute merge, number-grounding check (mocked LLM).", "implemented"),
    "tests/test_eval.py": ("Runs the offline known-answer evaluation inside pytest.", "implemented"),
    "docs/pdfkit.py": ("PDF layout toolkit used to build these documents.", "implemented"),
    "docs/build_pdf1.py": ("Builds this PDF.", "implemented"),
    "docs/build_pdf2.py": ("Builds the explanation & demo guide PDF.", "implemented"),
}


def tree_text() -> str:
    skip = {".venv", "__pycache__", ".pytest_cache", "logs", "screenshots", "evidence", ".claude"}
    lines = ["paymentlens/"]

    def walk(p: Path, prefix: str):
        items = sorted([x for x in p.iterdir() if x.name not in skip and not x.name.endswith(".pdf")],
                       key=lambda x: (x.is_file(), x.name))
        for i, x in enumerate(items):
            last = i == len(items) - 1
            lines.append(prefix + ("└── " if last else "├── ") + x.name + ("/" if x.is_dir() else ""))
            if x.is_dir():
                walk(x, prefix + ("    " if last else "│   "))
    walk(ROOT, "")
    lines.append("    (also: docs/evidence/ recorded outputs, docs/screenshots/, logs/ audit log - not expanded)")
    return "\n".join(lines)


def main():
    b = Book(OUT, "PaymentLens - Complete Code Architecture Guide",
             "How every file, function and number in PaymentLens works - a verified code walkthrough",
             "PDF 1 · Code Architecture Guide",
             ["This guide was generated from the actual repository (paymentlens/) after the code was written, tested and run. "
              "Code excerpts are extracted from the source files by function name; SQL, traces and numbers are loaded from "
              "docs/evidence/*.json, which scripts/capture_evidence.py recorded from real pipeline runs.",
              "Walkthrough runs are recorded with the offline rule-based parser so they are exactly reproducible. The OpenAI "
              f"path was also run live ({LLM_MODEL}): the known-answer evaluation scored "
              f"{EVAL_LLM['summary']['cases_passed']}/{EVAL_LLM['summary']['cases_total']} after three bugs found by that run were "
              "fixed (section 10), and AI mode produced the same numbers as offline mode.",
              "All data is synthetic (data/generate_data.py, seed 42) with deliberately planted scenarios and anomalies."])
    b.toc()

    # ===================================================================== 1
    b.h1("Project Overview")
    b.h2("What PaymentLens does")
    b.p("PaymentLens is a question-answering analytics application for payment performance. A business user types a question "
        "such as <i>\"Why did payment success rate fall last week?\"</i>. PaymentLens interprets it into a structured analysis "
        "request, compiles and validates SQL, runs it on a DuckDB database, decomposes the change into <b>traffic-mix shift</b> and "
        "<b>within-segment deterioration</b>, drills into the main driver, checks data quality and access rights, and returns an "
        "answer split into <b>observed facts</b>, <b>hypotheses</b> and <b>recommended next steps</b> - with the SQL and evidence "
        "behind every number.")
    b.p(f"For the main demo question the recorded answer is: success rate moved from <b>{pct(OV['previous']['value'])}</b> to "
        f"<b>{pct(OV['current']['value'])}</b> (<b>{pp(OV['delta'])}</b>); traffic mix explains <b>{pp(D['mix_effect'])}</b> and "
        f"within-segment deterioration <b>{pp(D['rate_effect'])}</b>; the strongest deteriorating segment is <b>{esc(NU['segment'])}</b> "
        f"({pct(NU['r0'])} → {pct(NU['r1'])}) with <b>{esc(DD['top_reason'])}</b> failures concentrated on {', '.join(DD['bad_days'])}.")
    b.h2("The problem it solves")
    b.bullets([
        "Leaders ask <i>why</i> a metric moved; analysts spend hours finding tables, writing queries and preparing explanations.",
        "A blended success rate can fall because segments got worse <i>or</i> because traffic moved to segments that are always "
        "worse (mix shift). A dashboard shows the fall but not which of the two happened.",
        "Generic text-to-SQL produces <i>a</i> query, but can silently use the wrong denominator, ignore duplicates, leak restricted "
        "columns or state guesses as facts.",
    ])
    b.h2("Main features and their status")
    b.table([["Feature", "Where in code", "Status"],
             ["Natural-language question → structured AnalysisIntent", "ai/intent_parser.py, ai/rule_parser.py", tag("implemented") + " (rule parser and OpenAI, both evaluated 20/20)"],
             ["Semantic layer: metric definitions, numerators, denominators", "config/metrics.yaml", tag("implemented")],
             ["Deterministic SQL compilation", "sqlengine/compiler.py", tag("implemented")],
             ["SQL guard (AST checks), read-only engine, timeout, cache", "sqlengine/guard.py, executor.py", tag("implemented")],
             ["Mix vs rate decomposition, counterfactual, Simpson check", "analytics/decomposition.py", tag("implemented")],
             ["Statistical significance (z-test, Wilson CI)", "analytics/stats.py", tag("implemented")],
             ["Automatic drill-down (decline reasons, bad days)", "core/pipeline.py::_root_cause", tag("implemented")],
             ["Data-quality gate with raw-vs-trusted impact", "analytics/data_quality.py", tag("implemented")],
             ["Transactions vs settlements reconciliation", "analytics/reconciliation.py", tag("implemented")],
             ["Role-based access: deny, restricted columns, row scope", "security/policy.py", tag("mocked") + " roles are simulated"],
             ["Audit log", "security/audit.py", tag("implemented")],
             ["Facts / hypotheses / recommendations + confidence", "analytics/insights.py", tag("implemented")],
             ["LLM narrative with number-grounding check", "ai/narrator.py", tag("implemented") + " (mocked tests + live run passed grounding)"],
             ["Known-answer evaluation", "scripts/run_eval.py", tag("implemented")],
             ["Multimodal inputs, real identity provider, warehouse connectors, forecasting", "-", tag("planned")]],
            [0.42, 0.30, 0.28])
    b.h2("Technology stack and why each was chosen")
    import duckdb as _d, sqlglot as _s, streamlit as _st, pydantic as _p, openai as _o, plotly as _pl
    b.table([["Technology", "Version installed", "Role", "Why this choice"],
             ["Python", sys.version.split()[0], "Everything", "Fast to build, rich data ecosystem."],
             ["DuckDB", _d.__version__, "Analytical database", "Embedded, fast SQL over local data, supports read-only mode and disabling external access."],
             ["pandas / NumPy / SciPy", f"{pd.__version__}", "Data generation, decomposition, statistics", "Vectorised maths; SciPy for the normal CDF in the z-test."],
             ["sqlglot", _s.__version__, "SQL parsing", "Real AST parsing for the SQL guard and the row-scope rewrite, instead of fragile string matching."],
             ["Pydantic", _p.__version__, "Schemas", "Validates the AnalysisIntent and LLM narrative; same schema used for OpenAI Structured Outputs."],
             ["OpenAI Python SDK", _o.__version__, "LLM access (optional)", "Responses API with text_format=&lt;Pydantic model&gt; returns parsed, validated objects."],
             ["Streamlit", _st.__version__, "UI", "Interactive data app in pure Python - right trade-off for a 48-hour build."],
             ["Plotly", _pl.__version__, "Interactive charts", "Hover tooltips, waterfall support."],
             ["PyYAML", "-", "Semantic layer / policies", "Business definitions live in reviewable config, not in code or prompts."],
             ["pytest", "-", "Tests", f"{N_TESTS} tests including ground-truth, safety and AI-regression tests."],
             ["reportlab, matplotlib", "-", "These PDFs", "Documentation build only."]],
            [0.17, 0.13, 0.22, 0.48])
    b.h2("What is AI-driven and what is deterministic")
    b.table([["Step", "AI or deterministic", "Fallback if AI is unavailable"],
             ["Understand the question → AnalysisIntent", "AI (OpenAI) when a key is configured", "Rule-based parser (ai/rule_parser.py) - same schema"],
             ["Detect requests for sensitive attributes", "Deterministic, ALWAYS (rule detector merged into any LLM result)", "n/a"],
             ["Access decisions, filter validation, time resolution", "Deterministic", "n/a"],
             ["SQL generation in guided mode", "Deterministic compiler from YAML", "n/a"],
             ["SQL in SQL Explorer natural-language mode", "AI (OpenAI) - then the same guard", "User types SQL directly"],
             ["All calculations, statistics, drivers, data quality", "Deterministic Python / SQL", "n/a"],
             ["Narrative wording", "AI (OpenAI), checked by number-grounding", "Template narrative from facts"]],
            [0.36, 0.34, 0.30])
    b.callout("<b>LLM ≠ calculator, LLM ≠ database authority, LLM ≠ security layer.</b> The LLM only interprets language "
              "and phrases the answer. Python and SQL calculate, YAML defines business meaning, policy code decides permissions.", "note",
              "Core design principle")
    b.h2("Overall system design in one paragraph")
    b.p("The Streamlit UI calls <font name='Consolas'>PaymentLens.run(question, role, use_llm)</font> in core/pipeline.py. The pipeline "
        "checks data freshness, parses the question into an AnalysisIntent, checks access policy, validates filter values, resolves "
        "dates, applies the query budget, then calls one of five analysis handlers. Every SQL statement goes through "
        "<font name='Consolas'>QueryService.run()</font> (guard → row-scope rewrite → read-only DuckDB → audit). After analysis, a "
        "data-quality gate runs, facts are built with the ids of the queries that produced them, a narrative is written (template or "
        "grounded LLM) and a confidence score is computed. The result object carries every intermediate artefact so the UI can show "
        "evidence, SQL and the timed pipeline trace.")

    # ===================================================================== 2
    b.h1("Complete Repository Structure")
    b.p("Folder tree of the actual repository (virtual environment, caches, logs and recorded evidence omitted):")
    b.code(tree_text(), "paymentlens/ (generated by walking the file system)")
    b.h2("File-by-file reference")
    b.p("Functions, imports and callers below are extracted automatically from the source with Python's <i>ast</i> module, so they "
        "match the code exactly. 'Called by' lists project files that import the module.")
    for rel in FILES:
        if rel not in PURPOSE:
            continue
        purpose, status = PURPOSE[rel]
        sigs = signature_list(rel)
        fn = "<br/>".join(esc(s if k != "class" else f"class {s}") + f" <font color='#52514e'>(line {ln})</font>"
                          for k, s, ln in sigs[:14]) or "-"
        if len(sigs) > 14:
            fn += f"<br/>... +{len(sigs) - 14} more"
        imps = ", ".join(project_imports(rel)) or "(standard / third-party libraries only)"
        cal = ", ".join(callers(rel, FILES)) or ("streamlit run (entry point)" if rel == "app.py" else
                                                  "run directly / pytest" if rel.startswith(("scripts", "tests", "data", "docs")) else "-")
        b.h3(f"{esc(rel)}  {tag(status)}")
        b.table([["Purpose", esc(purpose)], ["Functions / classes", fn], ["Imports (project)", esc(imps)], ["Called by", esc(cal)]],
                [0.2, 0.8], header=False, font=7.8)
    b.h2("Configuration and data files")
    b.table([["File", "Content"],
             ["config/metrics.yaml", "Semantic layer: 4 metrics (payment_success_rate, order_conversion_rate, successful_gmv, transaction_count), 7 dimensions, join snippets, sensitive attribute catalog, root-cause settings, query limits."],
             ["config/policies.yaml", "3 simulated roles (admin, business_analyst, regional_analyst_north): restricted columns, row scope, and per-table scope rules."],
             ["ai/prompts/*.md", "System prompts for intent parsing, narration and SQL Explorer generation (placeholders filled at runtime)."],
             ["data/paymentlens.duckdb", f"Generated database: transactions_raw ({GT['row_counts']['transactions_raw']:,} rows), view transactions ({GT['row_counts']['transactions_trusted']:,}), merchants ({GT['row_counts']['merchants']}), banks ({GT['row_counts']['banks']}), settlements ({GT['row_counts']['settlements']:,}), meta."],
             ["data/ground_truth.json", "Independent pandas answers used by tests and evaluation."],
             ["tests/eval_questions.json", "20 known-answer questions with expectations referencing ground truth."],
             ["reports/eval_report_rules.json", "Latest offline evaluation output."],
             [".env.example", "OPENAI_API_KEY (blank), OPENAI_MODEL, LLM_TIMEOUT_SECONDS. Copy to .env; never committed."]],
            [0.28, 0.72])

    # ===================================================================== 3
    b.h1("Complete End-to-End System Architecture")
    b.drawing(pipeline_diagram([
        ("User + Streamlit UI", "app.py · role, question", "data"),
        ("Freshness check", "data_quality.freshness()", "det"),
        ("Intent parser", "intent_parser.parse_question()", "ai"),
        ("Policy check (deny)", "policy.check_intent()", "sec"),
        ("Filter validation", "pipeline._canonical_filters()", "det"),
        ("Policy scope + time resolver", "check_intent() · resolve_periods()", "sec"),
        ("Query budget", "max days / dimensions", "sec"),
        ("Metric resolver + SQL compiler", "metrics.yaml · compile_metric()", "det"),
        ("SQL guard + row-scope rewrite", "validate_sql() · apply_row_scope()", "sec"),
        ("DuckDB (read-only)", "Executor.execute() · cache · timeout", "data"),
        ("Analysis engine", "decompose() · drivers · drill-down", "det"),
        ("Data-quality gate", "run_checks() · raw vs trusted", "det"),
        ("Facts + narrative", "build_facts() · narrate() (LLM/template)", "ai"),
        ("Confidence + response", "confidence() → AnalysisResult → UI", "det"),
    ]), "Request pipeline. Left column top-to-bottom, then right column bottom-to-top. Colours show which steps use AI.")
    b.h2("Components and their responsibilities")
    b.table([["Component", "Responsibility", "Input → Output"],
             ["Frontend (app.py)", "Collect question + role; render status, understanding, KPIs, DQ banner, cards, tabs.", "question, role → AnalysisResult rendered"],
             ["Intent parser", "Map language to a closed vocabulary; flag ambiguity and unsupported questions.", "str → AnalysisIntent"],
             ["Policy engine", "Deny restricted attributes; apply row scope; restricted columns list for the guard.", "AnalysisIntent, role → PolicyDecision"],
             ["Time resolver", "Relative words → concrete Period objects anchored on the last complete day.", "TimeSpec → Period(s) + assumptions"],
             ["Metric resolver", "Look up numerator/denominator/row filter for the metric in YAML.", "metric name → metric spec dict"],
             ["SQL compiler", "Build SQL from spec, periods, dimensions, filters.", "spec, periods, dims → CompiledQuery"],
             ["SQL guard", "AST checks; returns per-check pass/fail.", "SQL → GuardResult"],
             ["Query service", "Guard → rewrite → execute → audit.", "SQL → (DataFrame, QueryRecord)"],
             ["Executor", "Read-only DuckDB with timeout and cache.", "SQL → DataFrame, ms, cache_hit"],
             ["Analysis engine", "Decomposition, counterfactual, drivers, Simpson, drill-down.", "DataFrames → analysis dict + tables"],
             ["Data-quality gate", "Detect issues and quantify their impact.", "periods → dq dict"],
             ["Insights + narrator", "Facts with query ids → narrative (template or grounded LLM).", "analysis → Fact list, Narrative"],
             ["Audit", "Append every decision.", "event → logs/audit.jsonl"]],
            [0.2, 0.5, 0.3])
    b.h2("How the components communicate: the data structures")
    b.p("Components exchange typed objects defined in <font name='Consolas'>core/models.py</font>. Each object is produced by one step "
        "and consumed by the next:")
    b.code("question (str)\n"
           "  -> AnalysisIntent      (Pydantic; metric, analysis_type, TimeSpec, dimensions, filters, data_source, requested_attributes, ambiguities)\n"
           "  -> PolicyDecision      (ALLOWED / SCOPED / DENIED, notices, scoped_filters)\n"
           "  -> Period x2           (current / previous, inclusive dates)\n"
           "  -> ResolvedQuery       (metric + spec, periods, dims, filters, source table, role, assumptions, notices)\n"
           "  -> CompiledQuery       (purpose, sql)\n"
           "  -> GuardResult         (allowed, checks[], tables, AST tree)\n"
           "  -> QueryRecord + DataFrame (id Qn, sql, executed_sql, status, rows, elapsed_ms, cache_hit, checks)\n"
           "  -> Decomposition / analysis dict / tables\n"
           "  -> Fact[]              (id Fn, text, query_ids)\n"
           "  -> Narrative           (summary, observed, hypotheses[confidence, evidence], recommendations, grounding)\n"
           "  -> AnalysisResult      (status, message, everything above, confidence, warnings, trace[])", "Object flow")
    b.h2("Sequence diagram - root-cause question")
    b.drawing(sequence_diagram(
        ["app.py", "pipeline.py", "intent_parser\n/rule_parser", "policy.py", "compiler.py", "service.py\n(guard+exec)",
         "decomposition\n/stats", "insights\n/narrator"],
        [(0, 1, "run(question, role, use_llm)"), (1, 5, "freshness SQL (Q1, Q2)"), (5, 1, "last complete day"),
         (1, 2, "parse_question()"), (2, 1, "AnalysisIntent"), (1, 3, "check_intent()"), (3, 1, "ALLOWED / DENIED"),
         (1, 1, "_canonical_filters(), resolve_periods(), budget"), (1, 4, "compile_metric(4 dims, 2 periods)"),
         (4, 1, "CompiledQuery"), (1, 5, "run(sql) Q3"), (5, 5, "validate_sql → rewrite → execute → audit"),
         (5, 1, "DataFrame + QueryRecord"), (1, 6, "segment_table() + decompose()"), (6, 1, "Decomposition"),
         (1, 5, "trend + drill-down SQL (Q4-Q6)"), (1, 5, "data-quality SQL (Q7-Q13)"), (1, 7, "build_facts(), narrate()"),
         (7, 1, "Facts, Narrative"), (1, 0, "AnalysisResult")]),
        "Sequence of calls for 'Why did payment success rate fall last week?' (query ids match the recorded run).")
    b.h2("Data-flow view")
    b.bullets([
        "<b>transactions_raw</b> (messy source) → <b>transactions</b> view (dedup by txn_id keeping first ingested copy, valid statuses, "
        "created_at ≤ as-of) → all trusted analysis.",
        "<b>transactions_raw</b> is read only by data-quality checks and when the user explicitly asks for raw data.",
        "<b>merchants</b> joins for merchant_category; <b>banks</b> joins for bank names (LEFT JOIN, missing → 'UNKNOWN'); "
        "<b>settlements</b> joins on txn_id for reconciliation.",
        "Results flow back as pandas DataFrames, are aggregated in Python (decomposition per dimension from one base query) and become "
        "Facts that cite query ids (Q1...Qn) - the same ids shown in the UI's Evidence tab and the audit log.",
    ])

    # ===================================================================== 4
    b.h1("Exact Code Execution Flow")
    b.p("Example question: <b>\"Why did payment success rate fall last week?\"</b> · role <b>business_analyst</b> · offline parser. "
        "The table is the real pipeline trace recorded by <font name='Consolas'>PaymentLens._step()</font>; timings are from that run.")
    b.table([["#", "Step", "file::function", "Recorded detail", "ms"]] +
            [[str(i), esc(t["step"]), esc(t["component"]), esc(t["detail"]), f"{t['elapsed_ms']}"] for i, t in enumerate(M["trace"], 1)],
            [0.04, 0.17, 0.28, 0.43, 0.08], code_cols=(2,), font=7.6)
    steps = [
        ("Step 0 - UI submits the question", "app.py (Ask tab)",
         "PaymentLens.run(question, role, use_llm)", "question='Why did payment success rate fall last week?', role='business_analyst', use_llm=False (offline run recorded for reproducibility; AI mode gives the same numbers - section 10)",
         "AnalysisResult", "render_status / render_understanding / ... in app.py",
         "run() wraps _run() in try/except: QueryBlocked → status BLOCKED, QueryError → ERROR, any other exception → ERROR with message. The UI never crashes on analysis errors."),
        ("Step 1 - Check data freshness", "analytics/data_quality.py", "freshness(svc, as_of)",
         f"svc = QueryService(executor, role), as_of='{esc(GT['data_as_of'])}' (data as-of timestamp read from the meta table)",
         "dict: last_day, last_day_attempts, trailing_median_attempts, is_partial, last_complete_day, first_day, query_id",
         "parse_question (dates for the prompt) and resolve_periods (anchor date)",
         f"Recorded: last day {M['dq']['freshness']['last_day']} had {M['dq']['freshness']['last_day_attempts']} attempts vs median "
         f"{M['dq']['freshness']['trailing_median_attempts']:.0f} → partial → last complete day {M['dq']['freshness']['last_complete_day']}. "
         "Threshold = limits.freshness_partial_threshold (0.5)."),
        ("Step 2 - Understand the question", "ai/intent_parser.py → ai/rule_parser.py", "parse_question(question, catalog, as_of, data_start, last_complete, use_llm)",
         "catalog = valid filter values from PaymentLens.catalog() (one cached SQL)", "(AnalysisIntent, parser_used, notes, llm_meta)",
         "pipeline: unsupported check, policy, filters",
         "With a key: structured_call() to OpenAI; LLMUnavailable → rule parser. In both cases rule_parser.detect_sensitive() is merged in. Trend analyses always get 'day' as first dimension."),
        ("Step 3 - Security-first denial check", "security/policy.py", "check_intent(intent, role, {})",
         "intent.requested_attributes = [] here", "PolicyDecision(status='ALLOWED')", "pipeline continues",
         "If a requested attribute maps to a restricted column for the role → DENIED immediately, before filters are validated and before any analysis SQL."),
        ("Step 4 - Validate filter values", "core/pipeline.py", "_canonical_filters(intent)",
         "intent.filters (none here)", "(filters dict, unknown list)", "policy scope step",
         "Values are matched case-insensitively against the catalog (prefix match ≥3 chars, e.g. 'Zenith' → 'Zenith Bank'). Unknown values → status UNSUPPORTED listing valid values."),
        ("Step 5 - Policy scope", "security/policy.py", "check_intent(intent, role, filters)",
         "filters", "PolicyDecision with scoped_filters / notices", "resolve_periods",
         "For regional_analyst_north the region filter is forced to ['North'] and a notice is added."),
        ("Step 6 - Resolve time periods", "core/time_resolver.py", "resolve_periods(intent, last_complete_day, first_day, assumptions)",
         "TimeSpec(kind='last_full_week')", f"current = {M['resolved']['current']}, previous = {M['resolved']['previous']}",
         "budget step, compiler",
         "Raises TimeResolutionError (→ UNSUPPORTED) for invalid dates or a comparison period before the data starts. Root-cause always gets a comparison period."),
        ("Step 7 - Query budget", "core/pipeline.py", "_run (limits)", "requested_days(spec), number of user dimensions",
         "continue or BLOCKED", "analysis handler",
         "Requested length is measured BEFORE clamping to the data range, so 'last 120 days' is blocked (limit 90) instead of being silently shortened."),
        ("Step 8 - Root-cause base query", "core/pipeline.py → sqlengine/compiler.py → sqlengine/service.py",
         "_root_cause(res, svc) → compile_metric(...) → svc.run(sql, purpose)",
         "metric='payment_success_rate', dims=[bank, payment_method, merchant_category, region], periods=[current, previous], filters={}",
         f"DataFrame with {Q['Q3']['rows']} rows (period × 4 dims) + QueryRecord Q3", "segment_table(), decompose()",
         "The guard runs 13 checks; any failure raises QueryBlocked. Execution errors raise QueryError; timeouts raise QueryTimeout → QueryError."),
        ("Step 9 - Decomposition & drivers", "analytics/decomposition.py",
         "segment_table(df, ['bank','payment_method']) → decompose(seg, keys, min_n=200, alpha=0.05) → top_drivers(); simpson_check()",
         "aggregated DataFrame", "Decomposition dataclass (R0, R1, delta, rate_effect, mix_effect, interaction, counterfactual, residual, segments)",
         "dimension views, drill-down, facts",
         f"Recorded: residual {D['residual']:.1e} (reconciles = {D['reconciles']}). Per-dimension views are computed in pandas from the same base query - no extra SQL."),
        ("Step 10 - Trend and drill-down", "core/pipeline.py", "_root_cause (continued)",
         f"top significant rate driver = {esc(NU['segment'])}", "drill_reasons table (Q5), drill_daily table (Q6), bad_days",
         "facts, hypotheses",
         f"Bad day rule: daily rate < baseline − 3·√(baseline(1−baseline)/n). Recorded bad days: {', '.join(DD['bad_days'])}."),
        ("Step 11 - Data-quality gate", "analytics/data_quality.py", "run_checks(svc, periods, as_of, metric, filters, fresh)",
         "both periods", "dict: checks[], raw_vs_trusted, warnings", "facts, confidence, UI banner",
         f"Recorded raw {pct(M['dq']['raw_vs_trusted']['raw_rate'])} vs trusted {pct(M['dq']['raw_vs_trusted']['trusted_rate'])} "
         f"({M['dq']['raw_vs_trusted']['difference_pp']:+.2f}pp)."),
        ("Step 12 - Facts, narrative, confidence", "analytics/insights.py, ai/narrator.py",
         "build_facts(res) → template_narrative(res, facts, refs) → narrate(facts, draft, use_llm) → confidence(res)",
         "AnalysisResult", f"{len(M['facts'])} facts, Narrative(generated_by='{M['narrative']['generated_by']}'), confidence {M['confidence']['level']} ({M['confidence']['score']})",
         "UI", "LLM narrative is accepted only if the grounding check passes; otherwise the template is shown and the rejection is reported."),
    ]
    for title, file, func, params, ret, nxt, err in steps:
        b.h3(esc(title))
        b.table([["What runs", f"<font name='Consolas'>{esc(func)}</font> in <b>{esc(file)}</b>"],
                 ["Parameters", esc(params)], ["Returns", esc(ret)], ["Consumed by", esc(nxt)], ["Validation / errors", esc(err)]],
                [0.2, 0.8], header=False, font=8)
    b.h2("Recorded AnalysisIntent for the example")
    b.code(json.dumps(M["intent"], indent=2), "docs/evidence/main.json → intent")
    b.h2("All queries executed for the example")
    b.table([["Id", "Purpose", "Rows", "ms", "Status"]] +
            [[q["id"], esc(q["purpose"]), str(q["rows"]), f"{q['ms']}", q["status"]] for q in M["queries"]],
            [0.06, 0.66, 0.08, 0.1, 0.1], font=7.8)
    b.code(Q["Q3"]["sql"], "Q3 - compiled root-cause SQL (exact text executed for business_analyst; no row-scope rewrite for this role)")

    # ===================================================================== 5
    b.h1("Natural Language Processing and LLM Integration")
    b.h2("How the question is interpreted")
    b.p("PaymentLens never lets a model write SQL in guided mode. The model's only job is to choose names from a closed vocabulary "
        "and fill the <font name='Consolas'>AnalysisIntent</font> schema. Every field is required (nullable where optional) so the same "
        "Pydantic class works with OpenAI Structured Outputs in strict mode and with the rule parser.")
    b.code(source_of("core/models.py", "AnalysisIntent")[0], "core/models.py - AnalysisIntent (the contract)")
    b.h2("Which LLM / API is used")
    b.p(f"{tag('implemented')} Live-tested with <b>{esc(LLM_MODEL)}</b>. OpenAI Responses API via the official Python SDK, method <font name='Consolas'>client.responses.parse(model, "
        "instructions, input, text_format=AnalysisIntent)</font>. The model is configurable with OPENAI_MODEL in .env "
        "(.env.example suggests gpt-4.1-mini; any model supporting Structured Outputs can be used). The key is read lazily from .env "
        "by <font name='Consolas'>core/config.openai_settings()</font> and never logged or displayed.")
    b.code(source_of("ai/llm_client.py", "structured_call")[0], "ai/llm_client.py - structured_call()")
    b.h2("The prompt passed to the model")
    prompt = (EVID / "intent_system_prompt_rendered.md").read_text(encoding="utf-8")
    b.p("Template: <font name='Consolas'>ai/prompts/intent_system.md</font>. Placeholders are filled by "
        "<font name='Consolas'>build_system_prompt()</font> with metric definitions from YAML, valid filter values from the database, and "
        "the data's date range. The rendered prompt recorded for this dataset:")
    b.code(prompt, "Rendered system prompt (docs/evidence/intent_system_prompt_rendered.md)")
    b.p("The user message is the raw question. The response is parsed into AnalysisIntent by the SDK; schema violations raise "
        "<font name='Consolas'>ValidationError</font>, which triggers one retry and then LLMUnavailable.")
    b.h2("Unsupported questions")
    b.p(f"The model (or the rule parser) sets <font name='Consolas'>is_supported=false</font> with a reason. Recorded example - "
        f"<i>\"{esc(UNS['question'])}\"</i> → status <b>{UNS['status']}</b>: {esc(UNS['message'][:220])}...")
    b.h2("What happens when the LLM fails")
    b.bullets(["No key → note 'No OPENAI_API_KEY configured; used the rule-based parser.'",
               "Network/auth/rate-limit/refusal → LLMUnavailable(reason) → rule parser; the reason is shown under Assumptions.",
               "Invalid schema twice → LLMUnavailable → rule parser.",
               "LLM narrative containing a number or fact id not present in the computed facts → rejected, template narrative shown, rejection reported.",
               "These paths are covered by tests/test_ai_layer.py using monkeypatched clients (no network)."])
    b.code(source_of("ai/intent_parser.py", "parse_question")[0], "ai/intent_parser.py - parse_question()")
    b.h2("Number-grounding check for the LLM narrative")
    b.code(source_of("ai/narrator.py", "grounding_check")[0], "ai/narrator.py - grounding_check()")
    b.h2("The offline rule-based parser")
    b.p("<font name='Consolas'>ai/rule_parser.py</font> maps keywords to metric/analysis type, regexes to dates ('week of Oct 26', "
        "'Nov 2 to Nov 8', 'last 14 days', ISO dates), catalog values to filters, and has an explicit list of unsupported topics "
        "(intent, refunds, chargebacks, forecasts, profit, demographics). Unknown bank names are passed through so they can be reported. "
        f"{tag('partial')} It covers the documented question patterns; unusual phrasings may be misread - LLM mode is the general solution.")

    # ===================================================================== 6
    b.h1("Database and SQL Architecture")
    con = duckdb.connect(str(ROOT / "data" / "paymentlens.duckdb"), read_only=True)
    schema = {t: con.execute(f"DESCRIBE {t}").fetchall() for t in ("transactions_raw", "merchants", "banks", "settlements")}
    view_sql = con.execute("SELECT sql FROM duckdb_views() WHERE view_name = 'transactions'").fetchone()[0]
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("transactions_raw", "transactions", "merchants", "banks", "settlements")}
    con.close()
    b.h2("Datasets")
    b.table([["Table", "Rows", "Columns (name type)", "Role"]] +
            [[t, f"{counts[t]:,}", esc(", ".join(f"{c[0]} {c[1]}" for c in schema[t])),
              {"transactions_raw": "Raw payment attempts incl. planted anomalies", "merchants": "Merchant dimension incl. 2 restricted columns",
               "banks": "Bank dimension", "settlements": "Settlement records for successful attempts"}[t]] for t in schema] +
            [["transactions (VIEW)", f"{counts['transactions']:,}", "same as transactions_raw", "Trusted, de-duplicated view used for analysis"]],
            [0.16, 0.08, 0.52, 0.24], font=7.6)
    b.h2("ER diagram")
    b.drawing(er_diagram({
        "transactions (VIEW)": ["dedup by txn_id (first ingested)", "valid statuses only", "created_at <= as-of"],
        "transactions_raw": ["txn_id", "order_id, attempt_no", "merchant_id  → merchants", "bank_id  → banks", "payment_method",
                             "created_at, ingested_at", "amount, currency", "status, decline_reason", "region"],
        "merchants": ["merchant_id (PK)", "merchant_name", "category, region", "risk_tier, signup_date", "settlement_account  [restricted]",
                      "contact_email  [restricted]"],
        "banks": ["bank_id (PK)", "bank_name", "bank_type"],
        "settlements": ["settlement_id (PK)", "txn_id  → transactions", "merchant_id", "settlement_date, status", "gross, fee, net amount"],
    }), "Tables and relationships. Keys are logical (no enforced constraints in the generated DuckDB file).")
    b.h2("The trusted view")
    b.code(view_sql, "transactions view definition (read from DuckDB catalog)")
    b.h2("From structured intent to SQL")
    b.p("The compiler looks up the metric in YAML and assembles SELECT, FROM, JOIN, WHERE and GROUP BY from configured fragments. "
        "Joins are added only if a requested dimension or filter needs them. Filter values are escaped literals that were already "
        "validated against the catalog.")
    b.code(source_of("sqlengine/compiler.py", "compile_aggregate")[0], "sqlengine/compiler.py - compile_aggregate()")
    b.code(source_of("sqlengine/compiler.py", "compile_metric")[0], "sqlengine/compiler.py - compile_metric()")
    b.p("Order-level metrics use a CTE that collapses retries: one row per order with the first attempt's dimensions "
        "(<font name='Consolas'>arg_min(dim, created_at)</font>) and <font name='Consolas'>MAX(success)</font>.")
    b.h2("How queries are validated")
    b.table([["Check (guard.py)", "What it rejects"],
             ["parse", "SQL sqlglot cannot parse"], ["single_statement", "Stacked statements ('SELECT 1; DELETE ...')"],
             ["read_only_statement", "Anything whose root is not SELECT / UNION"],
             ["no_forbidden_commands", "INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, COPY, ATTACH, DETACH, INSTALL, PRAGMA, SET, EXPORT, ..."],
             ["no_forbidden_functions", "read_csv/parquet/json, glob, getenv, current_setting, duckdb_*, pragma_*, ..."],
             ["allowed_tables", "Tables other than transactions, transactions_raw, merchants, banks, settlements (CTEs allowed)"],
             ["no_qualified_names", "schema/catalog-qualified names (main.x)"],
             ["known_columns", "Columns not in the schema, not an alias, not a CTE"],
             ["restricted_columns", "Role-restricted columns anywhere in the query"],
             ["no_star_on_sensitive_table", "SELECT * touching merchants for restricted roles (COUNT(*) is allowed)"],
             ["join_conditions", "Joins without ON/USING (cartesian products)"], ["join_count", "More than 4 joins"]],
            [0.3, 0.7])
    b.p("After validation, <font name='Consolas'>security/policy.apply_row_scope()</font> replaces table references with filtered "
        "subqueries for scoped roles. Then <font name='Consolas'>Executor.execute()</font> runs it on a connection opened with "
        "<font name='Consolas'>read_only=True</font>, <font name='Consolas'>SET enable_external_access=false</font> and "
        "<font name='Consolas'>SET lock_configuration=true</font>, with a 5-second interrupt timer and a SHA-256 result cache keyed by "
        "data version + SQL.")
    regq = next(q for q in REG["queries"] if q["purpose"].startswith("Root cause"))
    b.code(regq["executed_sql"][:2400], "Same root-cause query for regional_analyst_north AFTER the row-scope rewrite (excerpt)")
    b.h2("Worked example: natural language → intent → SQL → result → analysis")
    seg = pd.read_csv(EVID / "main_segments.csv")
    nu = seg[seg.segment == "Nova Bank | UPI"].iloc[0]
    b.table([["Stage", "Recorded value"],
             ["Natural language", esc(M["question"])],
             ["Structured intent", f"metric=payment_success_rate, analysis_type=root_cause, current_period=last_full_week, comparison=previous_period, filters=[]"],
             ["Resolved periods", f"{M['resolved']['current']} vs {M['resolved']['previous']}"],
             ["Generated SQL", "Q3 above (period × bank × payment_method × merchant_category × region; numerator, denominator)"],
             ["Query result", f"{Q['Q3']['rows']} rows; e.g. aggregated segment Nova Bank | UPI: previous {int(nu.s0)}/{int(nu.n0)}, current {int(nu.s1)}/{int(nu.n1)}"],
             ["Analysis", f"R0 {pct(D['R0'])}, R1 {pct(D['R1'])}, Δ {pp(D['delta'])}; rate {pp(D['rate_effect'])}, mix {pp(D['mix_effect'])}; counterfactual {pct(D['counterfactual_rate'])}"],
             ["Answer summary", esc(M["narrative"]["summary"])]], [0.2, 0.8])

    # ===================================================================== 7
    b.h1("Metrics and Mathematical Logic")
    w4 = GT["weekly_success_rate"]["W4"]
    b.h2("Payment success rate")
    b.p("<b>Definition (config/metrics.yaml):</b> successful terminal attempts ÷ all terminal attempts. Terminal = status SUCCESS or "
        "FAILED. <b>Excluded:</b> PENDING (not final), USER_CANCELLED (customer abandoned), duplicate txn_id rows, invalid statuses, "
        "future timestamps. Each retry counts as its own attempt (gross, attempt-level metric).")
    b.p(f"<b>Example (recorded, week 9-15 Nov):</b> numerator {w4['successes']:,}, denominator {w4['attempts']:,} → "
        f"{w4['successes']:,} ÷ {w4['attempts']:,} = <b>{pct(w4['rate'])}</b>. In SQL: "
        "<font name='Consolas'>SUM(CASE WHEN t.status = 'SUCCESS' THEN 1 ELSE 0 END)</font> ÷ <font name='Consolas'>COUNT(*)</font> "
        "with <font name='Consolas'>WHERE t.status IN ('SUCCESS','FAILED')</font>.")
    b.p(f"<b>Order conversion rate</b> counts each order once (success if any attempt succeeded). Recorded for the same week: "
        f"<b>{pct(ORD['analysis']['overall']['current']['value'])}</b> - higher than attempt success because retries rescue some orders. "
        "This is why the denominator ambiguity matters and is surfaced to the user.")
    b.h2("Time-window comparison")
    b.p("Periods are inclusive date ranges converted to half-open timestamp ranges <font name='Consolas'>[start 00:00, end+1 00:00)</font>. "
        "The comparison period is the same length immediately before. 'Last week' = most recent complete Monday-Sunday week ending on "
        "or before the last complete day (computed by the freshness check, not the wall clock).")
    b.p(f"Change: ΔR = R<sub>1</sub> − R<sub>0</sub> = {pct(D['R1'])} − {pct(D['R0'])} = <b>{pp(D['delta'])}</b>. Significance: two-proportion z-test "
        f"(analytics/stats.py), recorded p {'< 0.001' if OV['p_value'] < 0.001 else '= %.3f' % OV['p_value']}.")
    b.h2("Segment notation")
    b.p("For each segment i (e.g. bank × payment method) and period t (0 = previous, 1 = current): n<sub>i,t</sub> terminal attempts, "
        "s<sub>i,t</sub> successes, share w<sub>i,t</sub> = n<sub>i,t</sub> / Σn<sub>t</sub>, rate r<sub>i,t</sub> = s<sub>i,t</sub>/n<sub>i,t</sub>. "
        "The blended rate is a weighted average: R<sub>t</sub> = Σ<sub>i</sub> w<sub>i,t</sub>·r<sub>i,t</sub>.")
    b.h2("Mix-shift vs within-segment deterioration (symmetric decomposition)")
    b.code("rate_effect_i = (w_i,0 + w_i,1)/2 * (r_i,1 - r_i,0)          # segment got better/worse, at average weight\n"
           "mix_effect_i  = ((r_i,0 + r_i,1)/2 - Rbar) * (w_i,1 - w_i,0)  # traffic moved into/out of segment\n"
           "Rbar          = (R_0 + R_1)/2\n"
           "SUM(rate_effect_i) + SUM(mix_effect_i) = R_1 - R_0  exactly (no residual)", "Formulas")
    b.p("Subtracting R-bar does not change the total (Σ(w<sub>i,1</sub> − w<sub>i,0</sub>) = 0) but makes per-segment mix values readable: "
        "moving traffic <i>into</i> a below-average segment is negative.")
    b.h3("Small hand example (tests/test_math.py::test_mix_and_rate_example_reconciles)")
    b.table([["Segment", "Prev n / s", "Prev share", "Prev rate", "Curr n / s", "Curr share", "Curr rate"],
             ["A", "800 / 760", "80%", "95%", "500 / 475", "50%", "95%"],
             ["B", "200 / 160", "20%", "80%", "500 / 350", "50%", "70%"],
             ["Total", "1000 / 920", "", "R<sub>0</sub> = 92.0%", "1000 / 825", "", "R<sub>1</sub> = 82.5%"]], [0.12, 0.15, 0.12, 0.13, 0.15, 0.12, 0.21])
    b.bullets(["ΔR = 82.5 − 92.0 = <b>−9.5pp</b>",
               "Rate effect: A = 0.65 × 0 = 0; B = 0.35 × (70 − 80) = <b>−3.5pp</b>",
               "R-bar = (92.0 + 82.5)/2 = 87.25%. Mix effect: A = (95 − 87.25) × (50 − 80)% = −2.325pp; B = (75 − 87.25) × (50 − 20)% = −3.675pp; total <b>−6.0pp</b>",
               "Check: −3.5 + (−6.0) = −9.5pp (reconciles) (asserted in the test)"])
    b.h3("Real result for the example question")
    b.table([["Quantity", "Value", "Meaning"],
             ["R<sub>0</sub> (02-08 Nov)", pct(D["R0"]), "Previous blended success rate"],
             ["R<sub>1</sub> (09-15 Nov)", pct(D["R1"]), "Current blended success rate"],
             ["ΔR", pp(D["delta"]), "Observed change"],
             ["Σ rate effect", pp(D["rate_effect"]), "Segments genuinely performed worse"],
             ["Σ mix effect", pp(D["mix_effect"]), "Traffic moved toward weaker segments"],
             ["Residual", f"{D['residual']:.1e}", "Floating-point zero → the split reconciles exactly"]], [0.2, 0.15, 0.65])
    b.image(EVID / "waterfall_main.png", 0.86, "Recorded decomposition for the example question (matplotlib render of real outputs).")
    b.h2("Counterfactual success rate")
    b.code("R_cf = SUM_i  w_i,0 * r_i,1        # current segment rates applied to the previous traffic mix\n"
           "R_cf - R_0 = SUM_i w_i,0 (r_i,1 - r_i,0)     # performance effect, previous-mix weights\n"
           "R_1 - R_cf = SUM_i (w_i,1 - w_i,0) r_i,1     # mix effect, current rates\n"
           "interaction I = SUM_i (w_i,1 - w_i,0)(r_i,1 - r_i,0)\n"
           "symmetric rate effect = (R_cf - R_0) + I/2 ;  symmetric mix effect = (R_1 - R_cf) - I/2", "Formulas")
    b.p(f"Hand example: R_cf = 0.8×95% + 0.2×70% = <b>90.0%</b>; performance −2.0pp, mix −7.5pp, I = 0.3 × (−10pp) = −3.0pp; "
        f"symmetric rate = −2.0 + (−1.5) = −3.5pp (reconciles).")
    b.p(f"Recorded: R_cf = <b>{pct(D['counterfactual_rate'])}</b>; performance (previous-mix weights) {pp(D['cf_rate_effect'])}, "
        f"mix (current rates) {pp(D['cf_mix_effect'])}, interaction {pp(D['interaction'])}. Symmetric: {pp(D['cf_rate_effect'])} + "
        f"{pp(D['interaction'] / 2)} = {pp(D['rate_effect'])} (reconciles). The UI shows both conventions and names them, so the numbers never "
        "appear to contradict each other.")
    b.h2("Bank-level and payment-method analysis")
    b.p(f"The base query is aggregated in pandas per driver dimension (bank, payment_method, merchant_category, region) and decomposed "
        f"separately. Recorded bank view: <b>{esc(BV['segment'])}</b> share {pct(BV['w0'])} → {pct(BV['w1'])}, rate {pct(BV['r0'])} → "
        f"{pct(BV['r1'])} (p = {BV['p_value']:.2f}, not significant), mix contribution {pp(BV['mix_effect'])}. Recorded joint-segment "
        f"driver: <b>{esc(NU['segment'])}</b> {pct(NU['r0'])} → {pct(NU['r1'])} ({pp(NU['rate_change'])}), rate contribution "
        f"{pp(NU['rate_effect'])}.")
    b.image(EVID / "contrib_main.png", 0.86, "Per-segment rate and mix contributions (recorded).")
    b.h2("Driver ranking and significance")
    b.bullets(["Segments are ranked by rate effect and by mix effect separately (top_drivers()).",
               "A segment is 'significant' only with ≥ 200 attempts in both periods and two-proportion z-test p < 0.05.",
               "The drill-down uses the strongest significant rate driver moving in the same direction as the total.",
               "Wording is always 'largest contributors', never 'causes' - this is contribution accounting."])
    b.code(source_of("analytics/stats.py", "two_proportion_z")[0], "analytics/stats.py - two_proportion_z()")
    b.h2("Simpson's paradox detection")
    sd = SIM["analysis"]["decomposition"]
    b.p("Rule (simpson_check): the aggregate changed significantly, no sizeable segment changed significantly in the same direction, and "
        "at least half of sizeable segments moved the opposite way.")
    b.p(f"Recorded (26 Oct-01 Nov vs 19-25 Oct): Δ {pp(sd['delta'])}, rate effect <b>{pp(sd['rate_effect'])}</b> (segments improved), "
        f"mix effect <b>{pp(sd['mix_effect'])}</b>. {esc(SIM['analysis']['simpson']['message'])}")
    b.image(EVID / "waterfall_simpson.png", 0.86, "Recorded Simpson's-paradox week: every segment improved, the total fell.")
    b.code(source_of("analytics/decomposition.py", "decompose")[0], "analytics/decomposition.py - decompose()")

    # ===================================================================== 8
    b.h1("Data Quality, Security and Exception Handling")
    dq = {c["check"]: c for c in M["dq"]["checks"]}
    b.h2("Data-quality checks (recorded for 02-15 Nov)")
    b.table([["Check", "Count", "Detection SQL idea", "Handling"]] +
            [[esc(c["check"]), str(c["count"]), {"Freshness": "daily volume vs trailing median", "Duplicate txn_id": "GROUP BY txn_id HAVING COUNT(*) > 1 on raw",
                                                 "Missing bank_id": "bank_id IS NULL", "Orphan bank_id": "LEFT JOIN banks ... IS NULL",
                                                 "Invalid status": "status NOT IN (valid list) on raw", "Future timestamps": "created_at > as-of on raw"}[c["check"]],
              esc(c["handling"])] for c in M["dq"]["checks"]], [0.16, 0.08, 0.32, 0.44])
    imp = M["dq"]["raw_vs_trusted"]
    b.p(f"<b>Impact quantification:</b> the same metric is compiled against transactions_raw and transactions for the current period: "
        f"raw {pct(imp['raw_rate'])} (n={imp['raw_denominator']:,}) vs trusted {pct(imp['trusted_rate'])} (n={imp['trusted_denominator']:,}) "
        f"= {imp['difference_pp']:+.2f}pp. This doubles as the '<b>two sources disagree</b>' scenario: the disagreement is shown and explained, "
        f"and the trusted source is used.")
    b.h2("Exception scenarios and their control flow")
    rows = [["Scenario", "Detected in", "Control flow", "User sees (recorded)"],
            ["Duplicate / missing records", "data_quality.run_checks", "Trusted view excludes duplicates; missing bank → UNKNOWN; impact computed", "Warning banner with raw vs trusted numbers"],
            ["Partially loaded last day", "data_quality.freshness", "last_complete_day = last_day − 1; periods anchored there", "Assumption '16 Nov is partially loaded and excluded'"],
            ["Restricted data requested", "policy.check_intent (before filters)", "status DENIED; no analysis SQL runs; audit event",
             esc(DEN["message"])],
            ["Data outside row scope", "policy.check_intent + apply_row_scope", "Region filter forced; every table rewritten to filtered subquery", esc("; ".join(REG["resolved"]["notices"]))],
            ["Unsafe SQL", "guard.validate_sql", "QueryBlocked → status BLOCKED (guided) or BLOCKED card (Explorer); audit", "Failed check names and reasons"],
            ["Expensive request", "pipeline budget, guard join checks, executor timeout", "BLOCKED before SQL; cartesian joins blocked; interrupt after 5 s", esc(BUD["message"])],
            ["Ambiguous period / denominator", "parser ambiguities + time resolver", "Default chosen and recorded as assumption; confidence reduced", "Ambiguity and assumption list"],
            ["Unsupported question", "parser is_supported=false", "status UNSUPPORTED + capabilities text", esc(UNS["message"][:120]) + "..."],
            ["Unknown filter value", "pipeline._canonical_filters", "status UNSUPPORTED with valid values", "e.g. 'Atlantis Bank' (tested)"],
            ["Failed query / timeout", "QueryService.run", "QueryError → status ERROR with DuckDB message; audit", "Error card"],
            ["LLM failure / bad output", "llm_client, narrator", "Fallback to rule parser / template; note shown", "Assumption note"],
            ["Database file missing", "Executor.__init__", "FileNotFoundError with instruction to run generate_data.py; app stops at startup", "Streamlit error page " + tag("partial")]]
    b.table(rows, [0.17, 0.2, 0.33, 0.3], font=7.6)
    b.code(source_of("security/policy.py", "check_intent")[0], "security/policy.py - check_intent()")
    b.code(source_of("security/policy.py", "apply_row_scope")[0], "security/policy.py - apply_row_scope()")
    b.code(source_of("sqlengine/service.py", "QueryService")[0], "sqlengine/service.py - QueryService (guard → rewrite → execute → audit)")

    # ===================================================================== 9
    b.h1("Detailed Walkthrough of Every Important Module")
    modules = [
        ("core/pipeline.py", ["_run", "_root_cause"], "Orchestrates all steps; each step wrapped in _step() which records (step, component, detail, ms). Handlers fill res.analysis and res.tables."),
        ("core/time_resolver.py", ["resolve_spec", "resolve_periods"], "Pure functions; every interpretation appended to the assumptions list."),
        ("sqlengine/guard.py", ["validate_sql"], "Returns a GuardResult with every check recorded, even passing ones, so the UI can show them."),
        ("sqlengine/executor.py", ["Executor"], "One read-only connection guarded by a lock; threading.Timer calls con.interrupt() on timeout."),
        ("analytics/data_quality.py", ["freshness"], "Freshness drives period anchoring; run_checks quantifies impact."),
        ("analytics/reconciliation.py", ["reconcile"], "Identity: successful = settled gross + mismatch on settled + pending + missing."),
        ("analytics/insights.py", ["confidence"], "Score starts at 100; deductions for fallback parser, ambiguity, DQ warnings, non-significance, small n, non-reconciliation."),
        ("ai/rule_parser.py", ["parse"], "Fallback parser producing the same schema; unsupported-topic list checked first."),
    ]
    for rel, names, note in modules:
        b.h2(rel)
        b.p(esc(note))
        b.table([["Signature", "Line"]] + [[esc(s), str(ln)] for k, s, ln in signature_list(rel) if k != "class"], [0.88, 0.12], code_cols=(0,), font=7.6)
        for n in names:
            code, a1, a2 = source_of(rel, n)
            if len(code.splitlines()) > 140:
                code = "\n".join(code.splitlines()[:140]) + "\n    ... (truncated here; see file)"
            b.code(code, f"{rel} lines {a1}-{a2} - {n}")

    # ===================================================================== 10
    b.h1("Testing and Validation")
    names = re.findall(r"(tests[\\/][\w]+\.py)::(\S+) PASSED", PYTEST)
    passed = re.search(r"(\d+) passed", PYTEST)
    by_file: dict[str, list[str]] = {}
    for f, t in names:
        by_file.setdefault(f.replace("\\", "/"), []).append(t)
    b.p(f"Recorded pytest run (docs/evidence/pytest_output.txt): <b>{passed.group(1) if passed else '?'} passed</b>, 0 failed.")
    b.table([["Test file", "Tests", "What is verified"]] +
            [[f, str(len(v)), esc(PURPOSE.get(f, ("", ""))[0])] for f, v in sorted(by_file.items())], [0.3, 0.08, 0.62])
    b.h2("Test inputs, expected and observed outputs (ground truth)")
    g = GT["w4_vs_w3_bank_x_method"]
    b.table([["Check", "Expected (data/ground_truth.json, pandas)", "Observed (pipeline)", "Tolerance"],
             ["W4 success rate", pct(GT["weekly_success_rate"]["W4"]["rate"]), pct(OV["current"]["value"]), "1e-12"],
             ["Δ W4 vs W3", pp(g["delta"]), pp(D["delta"]), "1e-12"],
             ["Rate effect", pp(g["rate_effect"]), pp(D["rate_effect"]), "1e-12"],
             ["Mix effect", pp(g["mix_effect"]), pp(D["mix_effect"]), "1e-12"],
             ["Counterfactual", pct(g["counterfactual_rate"]), pct(D["counterfactual_rate"]), "1e-12"],
             ["Top rate segment", g["top_negative_rate_segment"], NU["segment"], "exact"],
             ["Top mix bank", GT["w4_vs_w3_bank"]["top_negative_mix_segment"], BV["segment"], "exact"],
             ["Raw W4 rate", pct(GT["w4_raw_success_rate"]["rate"]), pct(RAW["analysis"]["overall"]["current"]["value"]), "1e-12"],
             ["Duplicate rows", str(GT["data_quality"]["duplicate_extra_rows"]), str(dq["Duplicate txn_id"]["count"]), "exact"],
             ["Order conversion W4", pct(GT["weekly_order_conversion"]["W4"]), pct(ORD["analysis"]["overall"]["current"]["value"]), "1e-3 (see known issues)"],
             ["Missing settlements W4", str(GT["planted"]["settlements"]["missing_settlement_records"]), str(int(REC["analysis"]["reconciliation"]["missing_settlement_txns"])), "exact"],
             ["Outage days", ", ".join(x[5:] for x in GT["planted"]["nova_upi_outage_days"]), ", ".join(DD["bad_days"]), "exact"]],
            [0.2, 0.3, 0.3, 0.2])
    b.h2("Known-answer evaluation")
    s = EVAL["summary"]
    b.p(f"scripts/run_eval.py, mode <b>{s['mode']}</b>, run {s['run_at']}: <b>{s['cases_passed']}/{s['cases_total']}</b> cases passed. "
        f"Intent accuracy {s['intent_accuracy']['passed']}/{s['intent_accuracy']['total']}, status {s['status_accuracy']['passed']}/{s['status_accuracy']['total']}, "
        f"numerical correctness {s['numerical_correctness']['passed']}/{s['numerical_correctness']['total']}, driver identification "
        f"{s['driver_identification']['passed']}/{s['driver_identification']['total']}, policy {s['policy_enforcement']['passed']}/{s['policy_enforcement']['total']}.")
    b.table([["Id", "Question", "Role", "Status", "Pass"]] +
            [[c["id"], esc(c["question"]), c["role"], c["status"], "yes" if c["passed"] else "NO"] for c in EVAL["cases"]],
            [0.06, 0.56, 0.18, 0.12, 0.08], font=7.6)
    b.callout("The rule-based parser was written alongside these 20 questions, so its 20/20 proves the engine computes correct answers "
              "for these phrasings - not that arbitrary phrasings are understood. The live OpenAI run below is the independent check of "
              "language understanding.", "honest")
    b.h2("Live AI-mode evaluation (OpenAI)")
    sl = EVAL_LLM["summary"]
    b.p(f"<font name='Consolas'>scripts/run_eval.py --llm</font>, model <b>{esc(LLM_MODEL)}</b>, run {sl['run_at']}: "
        f"<b>{sl['cases_passed']}/{sl['cases_total']}</b> cases passed.")
    b.table([["Measure", "Offline (rules)", "AI mode (OpenAI)"]] +
            [[k.replace("_", " "), f"{s[k]['passed']}/{s[k]['total']}", f"{sl[k]['passed']}/{sl[k]['total']}"]
             for k in ("intent_accuracy", "status_accuracy", "numerical_correctness", "driver_identification", "policy_enforcement")],
            [0.4, 0.3, 0.3])
    b.p("<b>The first live run scored 15/20.</b> It exposed three real integration bugs, each fixed and covered by a regression test:")
    b.table([["Bug found by the live run", "Effect", "Fix", "Regression test"],
             ["For 'why' questions the model listed all four driver dimensions", "Query budget (max 3) blocked 5 root-cause questions",
              "Root cause ignores a parsed list of more than two dimensions (it checks all driver dimensions itself) and records an assumption; prompt rule 8 tells the model to leave dimensions empty",
              "test_root_cause_not_blocked_when_parser_lists_all_dimensions"],
             ["Model returned metric = null for 'Which bank contributed most to the decline?'", "KeyError → status ERROR",
              "parse_question() defaults a missing metric to payment_success_rate with an ambiguity note; prompt rule 4 requires a metric",
              "test_llm_missing_metric_gets_default"],
             ["Model marked a bank-account request as unsupported", "User saw 'unsupported' instead of 'access denied'",
              "Policy denial check now runs before the unsupported check", "eval case E14 (AI mode)"]],
            [0.27, 0.2, 0.35, 0.18], font=7.6)
    g2 = MLLM["narrative"]["grounding"]
    b.p(f"<b>AI narrative check (recorded, docs/evidence/main_llm.json):</b> for the main question the parser was "
        f"<b>{MLLM['parser']}</b>, the narrative was written by the <b>{MLLM['narrative']['generated_by']}</b> and the "
        f"number-grounding check passed = <b>{g2.get('passed')}</b> (unmatched numbers: {g2.get('unmatched_numbers') or 'none'}). "
        f"Change computed: {pp(MLLM['analysis']['overall']['delta'])} - identical to the offline run. Summary written by the model: "
        f"<i>{esc(MLLM['narrative']['summary'])}</i>")
    b.h2("SQL security tests")
    b.p("tests/test_sql_guard.py blocks 17 malicious/expensive statements (DDL, DML, stacked statements, COPY, ATTACH, INSTALL, PRAGMA, "
        "read_csv, getenv, duckdb_settings(), meta table, qualified names, comma join, unknown column), blocks restricted columns for "
        "analysts, allows them for admin, verifies the row-scope rewrite for transactions and settlements, and verifies that the DuckDB "
        "connection itself rejects writes and file access even without the guard.")
    b.h2("Known issues and limitations")
    b.bullets([
        "Live OpenAI evaluation covers the same 20 questions only; wider phrasing coverage and repeated-run stability are not yet "
        "measured, and results can change with the chosen model. SQL Explorer natural-language mode was not part of the live evaluation.",
        "Rule parser coverage is limited to documented patterns.",
        "Order conversion attributes an order to its first attempt; retries crossing a period boundary differ slightly from the "
        "ground-truth convention (tolerance 1e-3 in tests).",
        "Mix/rate split depends on the segment grain (stated in the UI).",
        "Roles are simulated with a dropdown; no authentication. Query cost control uses limits and a timeout, not an optimiser cost model.",
        "Result cache is in-process and unbounded (fine for demo scale). One shared DuckDB connection guarded by a lock.",
        "Driver attribution is contribution accounting, not causal inference.",
    ])

    # ===================================================================== 11
    b.h1("Running the Project")
    b.p("Commands verified on Windows 11 with Python 3.13 during this build (PowerShell, from the folder containing paymentlens/).")
    b.code("cd paymentlens\n"
           "python -m venv .venv\n"
           ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n\n"
           "# optional AI mode\n"
           "copy .env.example .env        # then edit .env and set OPENAI_API_KEY=... and OPENAI_MODEL=...\n\n"
           "# generate synthetic data + ground truth (deterministic, seed 42)\n"
           ".\\.venv\\Scripts\\python.exe data\\generate_data.py\n\n"
           "# start the app -> http://localhost:8501\n"
           ".\\.venv\\Scripts\\python.exe -m streamlit run app.py\n\n"
           "# tests and evaluation\n"
           ".\\.venv\\Scripts\\python.exe -m pytest\n"
           ".\\.venv\\Scripts\\python.exe scripts\\run_eval.py\n"
           ".\\.venv\\Scripts\\python.exe scripts\\run_eval.py --llm     # needs a key\n\n"
           "# regenerate evidence and these PDFs\n"
           ".\\.venv\\Scripts\\python.exe scripts\\capture_evidence.py\n"
           ".\\.venv\\Scripts\\python.exe docs\\build_pdf1.py\n"
           ".\\.venv\\Scripts\\python.exe docs\\build_pdf2.py", "Setup and run")
    b.h2("Running the complete demo")
    b.bullets(["Start the app; keep role = Business Analyst.",
               "Click 'Why did success fall?' → walk through understanding, KPIs, DQ banner, cards, Root cause, Drill-down, Evidence & SQL.",
               "Click 'Mix-shift week (Oct 26)' → Simpson's paradox banner.",
               "Click 'Raw vs trusted data' and 'Merchant bank accounts' → data-quality and access-control failures.",
               "Switch role to Regional Analyst (North) and ask again → scoped answer and rewritten SQL in the Evidence tab.",
               "SQL Explorer → 'Drop a table (unsafe)' → BLOCKED with guard checks. Audit log tab shows every decision."], numbered=True)

    # ===================================================================== 12
    b.h1("Complete Technical Flow Summary")
    b.bullets([
        "<b>app.py</b> collects question + simulated role and calls <b>PaymentLens.run()</b>.",
        "<b>freshness()</b> finds the last complete day (partial days excluded).",
        "<b>parse_question()</b> builds an AnalysisIntent with OpenAI Structured Outputs or the rule parser; sensitive-attribute detection is always deterministic.",
        "<b>check_intent()</b> denies restricted requests first; filters are validated against the catalog; row scope is applied.",
        "<b>resolve_periods()</b> converts words into dates and records assumptions; the <b>budget</b> blocks oversized requests.",
        "<b>compile_metric()</b> turns YAML definitions into SQL; <b>QueryService.run()</b> validates it with <b>validate_sql()</b>, rewrites it with "
        "<b>apply_row_scope()</b>, executes read-only with timeout and cache, and audits it.",
        "<b>decompose()</b> splits the change into rate and mix effects that reconcile exactly; the counterfactual, significance tests, "
        "Simpson check and automatic drill-down identify and explain drivers.",
        "<b>run_checks()</b> reports data-quality issues with their numerical impact; <b>reconcile()</b> compares sources.",
        "<b>build_facts()</b> creates numbered facts tied to query ids; <b>narrate()</b> writes facts / hypotheses / recommendations, "
        "accepting an LLM version only if every number is grounded; <b>confidence()</b> explains how sure the answer is.",
        "The UI renders everything with the SQL, guard checks, assumptions and a timed trace, and every query is in logs/audit.jsonl.",
    ], numbered=True)
    b.callout("Because every step is deterministic except interpretation and phrasing, and both of those are validated or have "
              "fallbacks, any number on screen can be traced to a SQL query id, and the same question always gives the same answer.",
              "note", "Why the design is defensible")
    b.build()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
