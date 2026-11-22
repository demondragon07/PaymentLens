"""Builds the project explanation and demo guide PDF from recorded outputs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))

from pdfkit import Book, EVID, esc, ev, pct, pipeline_diagram, pp, tag  # noqa: E402

OUT = ROOT / "docs" / "PaymentLens_Complete_Project_Explanation_And_Demo_Guide.pdf"
SHOT = ROOT / "docs" / "screenshots"

M, SIM, RAW, DEN, REG, REC, UNS, BUD, BRK, ORD = (ev(k) for k in (
    "main", "simpson", "raw", "denied", "regional", "recon", "unsupported", "budget", "breakdown", "order"))
GT = json.loads((ROOT / "data" / "ground_truth.json").read_text(encoding="utf-8"))
EVAL = json.loads((ROOT / "reports" / "eval_report_rules.json").read_text(encoding="utf-8"))
EVAL_LLM = json.loads((ROOT / "reports" / "eval_report_llm.json").read_text(encoding="utf-8"))
import re  # noqa: E402
N_TESTS = int(re.search(r"(\d+) passed", (EVID / "pytest_output.txt").read_text(encoding="utf-8", errors="ignore")).group(1))
MLLM = ev("main_llm")
LLM_MODEL = MLLM.get("model", "configured OpenAI model")
LL = f"{EVAL_LLM['summary']['cases_passed']}/{EVAL_LLM['summary']['cases_total']}"
A, D, OV = M["analysis"], M["analysis"]["decomposition"], M["analysis"]["overall"]
DD, BV, NU = A["drilldown"], A["bank_view"]["top_mix"], A["drivers"]["rate"][0]
SD = SIM["analysis"]["decomposition"]
IMP = M["dq"]["raw_vs_trusted"]
FR = M["dq"]["freshness"]
RC = REC["analysis"]["reconciliation"]
P0, P1, DL = pct(OV["previous"]["value"]), pct(OV["current"]["value"]), pp(OV["delta"])
MIX, RATE, CF = pp(D["mix_effect"]), pp(D["rate_effect"]), pct(D["counterfactual_rate"])


FALLBACK = {
    3: "Expand the panel manually; if the app is frozen show screenshot 01_understanding.jpg.",
    4: "If the expander will not open, show the Q3 SQL printed in PDF 1 section 4.",
    5: "Use screenshot 02_kpis_dq.jpg; the numbers are in the cheat sheet.",
    6: "Skip to the Root cause tab - the segment table is also there.",
    7: "Use screenshot 04_waterfall.jpg or docs/evidence/waterfall_main.png.",
    8: "Read the numbers from the cheat sheet; screenshot 04_waterfall.jpg shows the counterfactual row.",
    9: "Show docs/evidence/trend_main.png (Nova UPI dip on 11-14 Nov) and the facts list in docs/evidence/main.json.",
    10: "Type the question manually; if it still fails show the yellow banner in screenshot 02_kpis_dq.jpg.",
    11: "Check the role dropdown shows Business Analyst; fallback screenshot 06_denied.jpg.",
    12: "Use screenshot 03_narrative.jpg.",
    13: "Close on the slides - the message does not depend on the app.",
}


def demo_step(b: Book, n: int, title: str, rows: dict):
    if "If it fails" not in rows:
        rows = {**rows, "If it fails": FALLBACK.get(n, "Use the matching screenshot in docs/screenshots.")}
    b.h3(f"Demo step {n}: {esc(title)}")
    b.table([[k, v] for k, v in rows.items()], [0.2, 0.8], header=False, font=8.2)


def qa(b: Book, n: int, q: str, short: str, detail: str, ref: str):
    b.h3(f"Q{n}. {esc(q)}")
    b.table([["Short answer", short], ["Technical detail", detail], ["Reference", ref]], [0.18, 0.82], header=False, font=8.2)


def main():
    b = Book(OUT, "PaymentLens - Project Explanation, Presentation & Live Demo Guide",
             "Everything you need to explain, present and demonstrate PaymentLens to teammates and judges",
             "PDF 2 · Explanation & Demo Guide",
             ["This guide explains PaymentLens from zero: the challenge, the story, the concepts, how it works, what makes it "
              "different, the slide-by-slide presentation, a step-by-step live demo, speaking scripts, failure demos, 32 judge "
              "questions, a factual implementation summary, a checklist and a one-page cheat sheet.",
              "Every number quoted comes from recorded runs of the actual application (docs/evidence/*.json) on the synthetic "
              f"dataset; screenshots were captured from the running app. Nothing is invented. Walkthrough numbers come from offline "
              f"runs (exactly reproducible); AI mode ({LLM_MODEL}) was evaluated live, scored {LL} and gave identical numbers.",
              "Hinglish boxes give an easy explanation in Hindi-English for quick revision."], accent="#eb6834")
    b.toc()

    # ===================================================================== 1
    b.h1("Understanding the Original Challenge")
    b.h2("The customer problem")
    b.p("A payments business keeps transaction, merchant, bank, payment-method and settlement data in several datasets. Leaders ask "
        "<i>why success rates changed, which segments caused a decline, and what to do</i>. Today analysts spend hours finding the "
        "right data, writing queries and preparing explanations.")
    b.h2("Existing manual process and pain points")
    b.bullets(["An analyst receives a question by message or in a meeting.",
               "They find the tables, check definitions with colleagues, write SQL, export to spreadsheets, make charts.",
               "They slice by bank, method and merchant until something 'looks like' the reason, then write a summary.",
               "<b>Pain points:</b> slow (hours to days); inconsistent definitions (which denominator?); data problems noticed late "
               "(duplicates, partial days); risk of exposing sensitive data; conclusions mix facts and guesses; hard to audit."])
    b.h2("What the challenge asks for")
    b.table([["Type", "Requirement (summarised)"],
             ["Core", "At least two related datasets; natural-language questions about metrics and trends; generate and execute SQL or "
                      "structured analysis; show the query / steps; charts or tables; cite dataset, filters and time window; separate "
                      "facts from hypotheses and recommendations."],
             ["Advanced", "Role-based access and query restrictions; data-quality checks and missing-data warnings; cohort comparison or "
                          "drill-down; query cost/timeout controls and caching; known-answer evaluation; confidence and uncertainty."],
             ["Failure scenarios", "Missing/duplicated records; request outside access scope; two sources disagree; decline explained by "
                                   "transaction-mix shift; ambiguous time period or denominator; expensive or unsafe query."],
             ["Minimum demo", "A business question answered from supplied data with an executed query, segmented analysis, visual "
                              "evidence and explicit caveats, plus one data-quality or access-control failure."]], [0.18, 0.82])
    b.h2("Requirement-by-requirement mapping")
    rows = [["Requirement", "How PaymentLens meets it", "Status"],
            ["≥ 2 related datasets", "transactions_raw + trusted view, merchants, banks, settlements (synthetic)", tag("mocked") + " data"],
            ["Natural-language questions", "Intent parser: OpenAI structured output or rule-based fallback", tag("implemented") + f" rules {EVAL['summary']['cases_passed']}/{EVAL['summary']['cases_total']} · OpenAI {LL}"],
            ["Generate & execute SQL", "Deterministic compiler + guard + read-only DuckDB; SQL Explorer for free SQL", tag("implemented")],
            ["Show query / steps", "Evidence & SQL tab (every query, guard checks), Pipeline trace tab", tag("implemented")],
            ["Charts / tables", "Waterfall, contributors, trend, drill-down, segment tables (Plotly)", tag("implemented")],
            ["Cite dataset, filters, window", "Evidence tab + 'How I understood your question' panel", tag("implemented")],
            ["Facts vs hypotheses vs recommendations", "Three separate cards; hypotheses carry confidence + evidence ids", tag("implemented")],
            ["RBAC + query restrictions", "3 simulated roles: deny, restricted columns, row-scope rewrite", tag("mocked") + " roles"],
            ["DQ checks + missing-data warnings", "6 checks + raw-vs-trusted impact + freshness", tag("implemented")],
            ["Cohort comparison / drill-down", "Period comparison, per-dimension views, automatic drill-down", tag("implemented")],
            ["Cost / timeout / caching", "90-day & 3-dimension budget, cartesian/join limits, 5 s timeout, result cache", tag("implemented")],
            ["Known-answer evaluation", f"20 questions, {EVAL['summary']['cases_passed']}/{EVAL['summary']['cases_total']} offline", tag("implemented")],
            ["Confidence & uncertainty", "p-values, 95% intervals, confidence score with reasons", tag("implemented")],
            ["Duplicates / missing records", f"{GT['data_quality']['duplicate_extra_rows']} duplicates detected, impact {IMP['difference_pp']:+.2f}pp", tag("implemented")],
            ["Outside access scope", "Merchant bank accounts → DENIED; regional analyst → scoped", tag("implemented")],
            ["Two sources disagree", "Raw vs trusted; transactions vs settlements reconciliation", tag("implemented")],
            ["Mix-shift decline", "Symmetric decomposition, counterfactual, Simpson detector", tag("implemented")],
            ["Ambiguous period / denominator", "Ambiguities listed, assumptions stated, confidence reduced", tag("implemented")],
            ["Expensive / unsafe query", "Budget block, SQL guard, read-only engine", tag("implemented")]]
    b.table(rows, [0.27, 0.5, 0.23], font=7.9)
    b.callout("Not built: real identity provider, connectors to production warehouses, multimodal input, forecasting, "
              "production deployment. These are listed as future scope.", "honest")

    # ===================================================================== 2
    b.h1("Project Story: From Problem to Solution")
    b.callout("This chapter separates <b>what actually happened</b> from a <b>suggested presentation narrative</b>. The documented "
              "history is only what is in the repository; no other timeline is claimed.", "honest")
    b.h2("Documented development facts")
    b.bullets(["Challenge 2 (Enterprise AI Business Analyst) was chosen over the merchant-onboarding challenge because it can be "
               "built and demonstrated end to end on local synthetic data, and its 'mix shift' scenario shows analytical reasoning.",
               "A research blueprint recommended an evidence-first design; PaymentLens follows its direction but changes several "
               "decisions (two metrics for the denominator, significance tests, row-level scope, number-grounding, freshness check, "
               "independent ground truth).",
               f"The build was done as a solo project; the code, {N_TESTS} tests, the evaluation and these documents are in the repository.",
               f"The first live AI-mode evaluation scored 15/20 and exposed three integration bugs (dimension list blocking 'why' "
               f"questions, missing metric crash, 'unsupported' shown instead of 'access denied'). All three were fixed with "
               f"regression tests; the re-run scored {LL}."])
    b.h2("Suggested narrative for the presentation")
    b.h3("1. The question every payments leader asks")
    b.p(f"\"Success rate dropped from {P0} to {P1}. Why?\" The honest answer needs more than a chart.")
    b.h3("2. Why a dashboard is not enough")
    b.p("A dashboard shows <i>that</i> the rate fell and maybe which bank is low. It cannot tell whether the bank got worse or just "
        "received more traffic, it does not check for duplicates or a half-loaded day, and it does not write the explanation.")
    b.h3("3. Why basic text-to-SQL is not enough")
    b.bullets(["It writes <i>a</i> query, not necessarily the <i>right</i> query (attempt-level or order-level? retries?).",
               "It runs whatever SQL the model produced - including slow or unsafe SQL, or SQL that reads restricted columns.",
               "It returns numbers without saying whether data was dirty or whether the change is just noise.",
               "Its explanation can contain numbers the model invented."])
    b.h3("4. What PaymentLens adds")
    b.bullets(["A <b>semantic layer</b>: exact metric definitions the model must choose from.",
               "<b>Deterministic SQL</b> with an AST guard, read-only engine, budget, timeout and audit.",
               "<b>Root-cause maths</b>: mix vs rate decomposition, counterfactual, significance tests, Simpson detector, drill-down.",
               "<b>Trust features</b>: data-quality gate with numeric impact, freshness check, access control, facts/hypotheses/"
               "recommendations, confidence score, number-grounded AI narrative."])
    b.h2("The most important design decisions")
    b.table([["Decision", "Why"],
             ["LLM produces a structured intent, not SQL", "Prevents wrong-metric and unsafe SQL; answers are repeatable and testable."],
             ["Everything works without the LLM", "Demo cannot break on network/API problems; the maths is never AI-dependent."],
             ["Every query goes through one governed service", "One place for validation, scoping, timeout, cache and audit."],
             ["Security does not trust the LLM", "Sensitive-attribute detection is deterministic and always merged."],
             ["Show uncertainty instead of hiding it", "Ambiguities, assumptions, p-values and confidence reasons are on screen."],
             ["Ground truth computed independently", "Tests compare against pandas results the app did not produce."]], [0.38, 0.62])

    # ===================================================================== 3
    b.h1("Understanding PaymentLens from Zero")
    concepts = [
        ("Payment transaction (attempt)", "One try to pay. If it fails, the customer may retry - that is a new attempt for the same order.",
         "You tap UPI at checkout, it fails, you tap again and it works: 2 attempts, 1 order.",
         "transactions table: txn_id (attempt) and order_id (order); attempt_no 1 or 2.",
         "Ek payment try = ek attempt. Fail hua aur dobara try kiya to naya attempt, order same."),
        ("Payment success rate", "Successful attempts divided by attempts that reached a final result.",
         f"Week 9-15 Nov: {GT['weekly_success_rate']['W4']['successes']:,} successes out of {GT['weekly_success_rate']['W4']['attempts']:,} final attempts = {pct(GT['weekly_success_rate']['W4']['rate'])}.",
         "config/metrics.yaml defines it; PENDING and USER_CANCELLED are excluded from the denominator.",
         "Kitne final attempts mein se kitne successful - wahi success rate."),
        ("Text-to-SQL", "Turning a question in English into a database query.",
         "'Success rate by bank last week' becomes SELECT ... GROUP BY bank.",
         "PaymentLens does it in two steps: question → structured intent (AI or rules) → SQL (our compiler). The AI never writes the guided SQL.",
         "Sawal ko SQL mein badalna. Hum AI se seedha SQL nahi likhwaate, pehle structured intent banate hain."),
        ("DuckDB", "A fast analytics database that runs inside the Python program - no server needed.",
         "Like SQLite, but built for big aggregations.",
         "Opened read-only with file/network access disabled; ~91k rows answer in milliseconds.",
         "Chhota par tez database jo app ke andar hi chalta hai."),
        ("Semantic layer", "A written dictionary of business metrics: exactly what is counted, how, and what is excluded.",
         "'Success rate' = SUCCESS ÷ (SUCCESS + FAILED), not ÷ all rows.",
         "config/metrics.yaml - shown beside every answer.",
         "Metric ki official definition ek jagah likhi hai, taaki galat denominator na lage."),
        ("Root-cause analysis", "Finding which parts of the business explain a change.",
         f"The fall of {DL} is mostly explained by Zenith traffic growth and Nova Bank UPI failures.",
         "Decomposition across bank × payment method, per-dimension views, automatic drill-down.",
         "Change kis wajah se aaya - kaun se segment ne kitna contribute kiya."),
        ("Transaction-mix shift", "The overall rate changes because the <i>mix</i> of traffic changed, even if each part performs the same.",
         f"Zenith Bank (≈80% success) went from {pct(BV['w0'])} to {pct(BV['w1'])} of traffic; its own rate barely moved, but the average fell.",
         f"Mix effect {MIX} in the example; Simpson detector flags pure mix-shift weeks.",
         "Bank kharab nahi hua, bas kam-success wale bank par traffic zyada chala gaya - average gir gaya."),
        ("Counterfactual", "A 'what if' calculation: what would the rate be if one thing had not changed?",
         f"If the traffic mix had stayed like last week, this week's rate would be {CF} instead of {P1}.",
         "R_cf = Σ previous share × current rate (analytics/decomposition.py).",
         "Agar traffic ka mix purana hi rehta to rate kitna hota - yeh 'what if' hai."),
        ("Evidence-backed analysis", "Every statement can be traced to a query and its data.",
         "Fact F5 cites query Q3; the Evidence tab shows Q3's SQL.",
         "Facts carry query ids; SQL, filters, periods and guard checks are displayed; LLM text is number-checked.",
         "Har number ka saboot - kaunsi query, kaunsa data, kaunsa filter."),
        ("Data-quality checks", "Automatic checks that the data is complete, unique, valid and fresh before trusting a number.",
         f"500 duplicate failed rows would make the rate look {abs(IMP['difference_pp']):.2f}pp worse than reality.",
         "analytics/data_quality.py runs 6 checks and computes raw vs trusted impact.",
         "Data ganda ho to answer galat hoga - isliye pehle data check, phir answer."),
    ]
    for i, (name, simple, example, inpl, hing) in enumerate(concepts, 1):
        b.h2(name)
        b.table([["Simple explanation", simple], ["Real-world example", example], ["In PaymentLens", inpl]], [0.2, 0.8], header=False)
        b.callout(hing, "hinglish")

    # ===================================================================== 4
    b.h1("Complete Project Working")
    b.p("Example question: <b>\"Why did payment success rate decline compared with the previous week?\"</b> (role: Business Analyst). "
        "This phrasing produces the same intent and numbers as the recorded main run - verified by evaluation case E03.")
    b.drawing(pipeline_diagram([
        ("1. You ask", "question + role", "data"), ("2. Freshness check", "is the last day complete?", "det"),
        ("3. Understand", "metric, period, type", "ai"), ("4. Access check", "allowed for this role?", "sec"),
        ("5. Dates", "which weeks exactly", "det"), ("6. Budget", "not too big?", "sec"),
        ("7. Build SQL", "from the metric dictionary", "det"), ("8. Check SQL", "safe, allowed columns", "sec"),
        ("9. Run", "read-only DuckDB", "data"), ("10. Analyse", "mix vs rate, drivers", "det"),
        ("11. Data quality", "duplicates, missing", "det"), ("12. Explain", "facts / hypotheses / actions", "ai")]),
        "The journey of one question, in plain words.")
    steps = [
        ("User input", "You type the question and press Analyse (or click the example button).", "app.py"),
        ("Question understanding", f"PaymentLens checks the data first: {FR['last_day']} has only {FR['last_day_attempts']} attempts (normal ≈ {FR['trailing_median_attempts']:.0f}), so it is still loading and is ignored.", "analytics/data_quality.py::freshness"),
        ("Intent extraction", "The parser decides: metric = Payment Success Rate (attempt level), analysis = root cause, current = last full week, compare with previous week. It notes two ambiguities ('success' could be order-level; 'last week' could be 7 days).", "ai/intent_parser.py"),
        ("Access check", "Business Analyst may see aggregated performance - allowed.", "security/policy.py"),
        ("Dates", f"Current {M['resolved']['current']}; previous {M['resolved']['previous']}.", "core/time_resolver.py"),
        ("SQL generation", "The compiler writes one SQL that counts successes and attempts for both weeks by bank, method, category and region.", "sqlengine/compiler.py"),
        ("Query validation", "The SQL guard parses it and runs 13 checks (SELECT only, allowed tables, no restricted columns, joins have conditions...).", "sqlengine/guard.py"),
        ("Database execution", f"DuckDB (read-only) returns {[q for q in M['queries'] if q['id'] == 'Q3'][0]['rows']} rows in about {[q for q in M['queries'] if q['id'] == 'Q3'][0]['ms']:.0f} ms. The query is logged in the audit log.", "sqlengine/executor.py"),
        ("Metric calculation", f"Previous {P0}, current {P1}, change {DL}; statistically significant (p < 0.001).", "core/pipeline.py, analytics/stats.py"),
        ("Segment comparison", "Every bank × payment-method segment gets its share and success rate in both weeks.", "analytics/decomposition.py"),
        ("Root-cause analysis", f"Split: mix {MIX} + rate {RATE} = {DL}. Biggest rate driver: {NU['segment']} ({pct(NU['r0'])} → {pct(NU['r1'])}). Biggest mix driver: {BV['segment']} share {pct(BV['w0'])} → {pct(BV['w1'])}.", "analytics/decomposition.py"),
        ("Drill-down", f"For {DD['segment']}: {DD['top_reason']} failures went {DD['reason_prev']} → {DD['reason_cur']}; bad days {', '.join(DD['bad_days'])}.", "core/pipeline.py::_root_cause"),
        ("Chart creation", "Waterfall (previous → mix → rate → current), contributor bars, daily trend, decline-reason bars.", "app.py (Plotly)"),
        ("Evidence generation", f"{len(M['facts'])} numbered facts, each tied to query ids; data-quality warnings with impact ({IMP['difference_pp']:+.2f}pp raw vs trusted).", "analytics/insights.py, data_quality.py"),
        ("Final business explanation", esc(M["narrative"]["summary"]) + " Hypotheses: issuer availability problem at Nova Bank UPI; traffic shift to Zenith Bank. Recommendations: check Nova logs for the bad days, review routing to Zenith, fix duplicate ingestion.", "ai/narrator.py (template here)"),
    ]
    b.table([["Stage", "What happens (recorded run)", "Code"]] + [[s, t, f"<font name='Consolas' size='7.4'>{esc(c)}</font>"] for s, t, c in steps],
            [0.18, 0.56, 0.26])
    b.image(SHOT / "01_understanding.jpg", 0.92, "Screenshot: 'How I understood your question' panel (captured from the running app).")
    b.image(SHOT / "02_kpis_dq.jpg", 0.92, "Screenshot: KPIs and data-quality warnings.")
    b.image(SHOT / "03_narrative.jpg", 0.92, "Screenshot: answer split into 'What the data shows' (facts), 'Possible explanations' (hypotheses) and 'Recommended next steps'.")
    b.image(SHOT / "04_waterfall.jpg", 0.92, "Screenshot: Root cause tab - waterfall, contributors, counterfactual.")
    b.callout("Pehle data check, phir sawal samjho, phir permission, phir safe SQL, phir maths, phir explanation - har step ka "
              "saboot screen par dikhta hai. AI sirf samajhta aur likhta hai; calculation Python/SQL karta hai.", "hinglish")

    # ===================================================================== 5
    b.h1("Features That Make Our Project Different")
    feats = [
        ("Root-cause decomposition", "implemented", "Splits the change into the part caused by segments getting worse and the part caused by traffic moving.",
         "Leaders need to know whether to fix a bank/integration or a routing decision.", "Symmetric two-period formula over bank × method; exact reconciliation (residual ≈ 0).",
         f"Turns '{DL}' into '{RATE} performance + {MIX} mix'.", "Root cause tab: waterfall + 'Residual (must be ~0)'.",
         "Why symmetric? Is it causal? What if you segment differently?"),
        ("Mix shift vs real deterioration + Simpson detector", "implemented", "Detects when the total falls while segments are stable or improving.",
         "Prevents blaming teams for a change that is only a mix effect.", "simpson_check(): significant total change, no significant segment change in the same direction, most segments opposite.",
         f"Week of 26 Oct: total {pp(SD['delta'])}, segments {pp(SD['rate_effect'])}, mix {pp(SD['mix_effect'])}.", "Click 'Mix-shift week (Oct 26)' → red Simpson banner.",
         "How do you avoid flagging noise? (significance + minimum volume)"),
        ("Counterfactual", "implemented", "'What would the rate be at last week's traffic mix?'", "Intuitive check of the decomposition for non-technical people.",
         "R_cf = Σ w_prev × r_curr, shown with the interaction term so conventions do not conflict.", f"{CF} vs {P1} actual.",
         "Root cause tab → Counterfactual row.", "Why do the two methods give slightly different numbers?"),
        ("Metric definitions (semantic layer)", "implemented", "One written definition of each metric, shown with the answer.",
         "Wrong denominators are the most common analytics error.", "config/metrics.yaml; the AI may only choose names.",
         f"Attempt success {P1} vs order conversion {pct(ORD['analysis']['overall']['current']['value'])} - both available, never confused.",
         "Understanding panel; Definitions tab.", "Who owns these definitions in production?"),
        ("Data-quality warnings with impact", "implemented", "Finds duplicates, missing ids, invalid rows, future timestamps, partial days - and shows how much they change the answer.",
         "A warning without impact is ignored; a number is acted on.", "Same metric on raw and trusted data; freshness vs median volume.",
         f"Raw {pct(IMP['raw_rate'])} vs trusted {pct(IMP['trusted_rate'])}.", "Yellow banner; 'Raw vs trusted data' example.",
         "Why keep missing-bank rows? (they are real payments; shown as UNKNOWN)"),
        ("Explainable evidence panel", "implemented", "Every query, its SQL, guard checks, rows, time and cache hit; facts tied to query ids; timed pipeline trace.",
         "Lets an analyst audit the answer in seconds.", "QueryRecord + Fact.query_ids + TraceStep.", f"{len(M['queries'])} queries for the main question.",
         "Evidence & SQL tab; Pipeline trace tab.", "Can a user change the SQL? (SQL Explorer, still guarded)"),
        ("Query safety", "implemented", "AST-based guard plus a read-only, network-less database, budget and timeout.",
         "LLM-written or user-written SQL must never damage or leak data.", "sqlglot checks; DuckDB read_only + external access disabled + locked config; 5 s interrupt.",
         "17 malicious statements blocked in tests.", "SQL Explorer → 'Drop a table (unsafe)'.", "What if the guard has a bug? (the engine still refuses writes/files)"),
        ("Role-based restrictions", "mocked", "Denies restricted data; restricts columns; limits a regional analyst to their region by rewriting SQL.",
         "Enterprise data access is never all-or-nothing.", "policy.check_intent + guard restricted columns + apply_row_scope.",
         esc(DEN["message"]), "'Merchant bank accounts' example; switch role to Regional Analyst.", "Is this real authentication? (no - simulated roles)"),
        ("Fact vs hypothesis separation + grounded AI text", "implemented", "Three cards: observed facts, hypotheses with confidence and evidence, next steps. LLM text is rejected if it adds numbers.",
         "Stops correlation being presented as certainty and stops invented numbers.", "insights.template_narrative + narrator.grounding_check.",
         "Hypothesis confidence 'medium' with evidence F5, F7, F8.", "Answer cards; caption under the cards.", "How do you know the LLM didn't hallucinate?"),
    ]
    for name, st, what, why, how, value, demo, jq in feats:
        b.h2(name)
        b.p(tag(st))
        b.table([["What it does", what], ["Why it matters", why], ["How it works", how], ["Value (recorded)", value],
                 ["How to demonstrate", demo], ["Judges may ask", jq]], [0.2, 0.8], header=False, font=8.4)

    # ===================================================================== 6
    b.h1("Hackathon PPT Content - Slide by Slide")
    b.p("Ten slides. Slide text is short on purpose; the speaker notes carry the detail. Visuals named here exist in "
        "docs/screenshots and docs/evidence.")
    slides = [
        ("PaymentLens - an AI analyst you can check", ["Why did payment success change - and can I trust the answer?",
         "Evidence-first AI for payment performance", "Name · Challenge 2 · Enterprise AI Business Analyst"],
         "Logo-style title; small screenshot of the answer cards (03_narrative.jpg).",
         "Hi, I'm [name]. I built PaymentLens for the Enterprise AI Business Analyst challenge. In one line: it's an AI analyst that tells you why payment success changed - and shows the proof for every number.",
         "Let me start with the problem."),
        ("The problem", ["Leaders ask: why did success rate drop?", "Analysts need hours: find data, write SQL, slice, explain",
         "Risks: wrong denominator, dirty data, data leaks, guesses stated as facts"],
         "Simple flow: question → hours of manual work → explanation of uncertain quality.",
         "Every payments team gets this question every week. The analyst finds tables, writes queries, slices by bank and method, and writes a summary. It's slow, and the answer is only as good as the definitions and data used.",
         "Why don't today's tools solve it?"),
        ("Why dashboards and text-to-SQL fall short", ["Dashboards show WHAT changed, not WHY", "Text-to-SQL writes A query, not necessarily the RIGHT one",
         "No data checks, no access control, numbers can be invented"],
         "Two-column comparison table.",
         "A dashboard shows the drop. A basic text-to-SQL chatbot writes a query - but it might use the wrong denominator, run unsafe SQL, or explain with numbers the model made up. Nobody can audit it.",
         "So here is what I built instead."),
        ("PaymentLens: the solution", ["AI understands the question; Python & SQL do the maths", "Separates mix shift from real deterioration",
         "Checks data quality and access before answering", "Shows facts, hypotheses, next steps - with the SQL behind them"],
         "Screenshot 01_understanding.jpg or 03_narrative.jpg.",
         "PaymentLens turns the question into a structured request, compiles safe SQL from a metric dictionary, runs it read-only, decomposes the change, checks data quality and permissions, and answers in three clearly separated parts.",
         "Let me show how it is built."),
        ("Architecture", ["12-step pipeline, one governed path to the database", "AI only in 2 places - both with fallbacks",
         "DuckDB read-only · sqlglot guard · Pydantic schemas · Streamlit"],
         "Pipeline diagram (Figure in PDF 1, section 3).",
         "The LLM is used only to understand the question and to phrase the answer. Everything else is deterministic. Every SQL query goes through one service that validates, scopes, times out, caches and logs it.",
         "Here's what happens inside for one question."),
        ("How one question is answered", ["Question → intent (metric, period, comparison)", "Intent → SQL from metrics.yaml → guard → DuckDB",
         "Decompose · test significance · drill down", "Facts → hypotheses → recommendations → confidence"],
         "The 12-box journey diagram (PDF 2, section 4).",
         f"For 'why did success rate fall last week', it finds the last complete week, compares {M['resolved']['current']} with the week before, runs {len(M['queries'])} validated queries and produces {len(M['facts'])} evidence-linked facts.",
         "What makes this different from other teams' chatbots?"),
        ("What makes it different", ["Mix vs rate decomposition + counterfactual", "Simpson's-paradox detector", "Data-quality impact (raw vs trusted)",
         "Access control with SQL rewriting", "Number-grounded AI narrative"],
         "Waterfall chart (waterfall_main.png).",
         f"The signature feature: success fell {DL}; {MIX} is traffic moving to Zenith Bank, {RATE} is real deterioration, mostly Nova Bank UPI. The two add up exactly.",
         "Let me show it live."),
        ("Results and live demo", [f"{P0} → {P1} ({DL})", f"Mix {MIX} · rate {RATE} · counterfactual {CF}",
         f"Driver: {NU['segment']} {pct(NU['r0'])} → {pct(NU['r1'])}, {DD['top_reason']} on {DD['bad_days'][0]}-{DD['bad_days'][-1]}",
         f"Tests: {N_TESTS} passed · known-answer eval {EVAL['summary']['cases_passed']}/{EVAL['summary']['cases_total']} offline, {LL} with OpenAI"],
         "Live app; backup screenshots 04_waterfall.jpg, 05_simpson.jpg.",
         "[Switch to the live demo - section 7.] All numbers come from synthetic data with planted scenarios, and the tests compare the app's answers with independently computed ground truth.",
         "How do we keep it reliable and safe?"),
        ("Reliability, security and limitations", ["Read-only DB, SQL guard, budget, timeout, audit log", "Denies restricted data; scopes regional users",
         "Works offline if the AI fails", "Limits: synthetic data, simulated roles, contribution ≠ causation"],
         "Screenshots 06_denied.jpg and 07_sql_blocked.jpg.",
         f"I want to be clear about limits: the data is synthetic, roles are simulated, and driver analysis shows contributions, not proven causes. The AI mode scored {LL} on our known-answer questions, but that is still a small question set.",
         "Finally, the impact and what's next."),
        ("Impact, future scope and conclusion", ["Hours of analyst work → seconds, with an audit trail", "Next: real warehouse, SSO roles, alerting, more metrics, LLM eval at scale",
         "PaymentLens: an AI analyst you can check"], "Closing screenshot of the answer cards.",
         "PaymentLens turns a recurring, hours-long analysis into a seconds-long, auditable answer. Next steps would be connecting to the real warehouse, real single sign-on roles, proactive alerts and a larger evaluation set. Thank you - happy to take questions.", "Q&amp;A."),
    ]
    for i, (title, content, visual, say, trans) in enumerate(slides, 1):
        b.h2(f"Slide {i}: {title}")
        b.table([["Slide content", "<br/>".join("• " + c for c in content)], ["Visual", visual]], [0.2, 0.8], header=False, font=8.4)
        b.callout(say, "say", "Speaker notes - say this")
        b.p(f"<b>Emphasise:</b> {'the AI never does the maths' if i in (4, 5) else 'the exact numbers and that they reconcile' if i in (7, 8) else 'honesty about limits' if i == 9 else 'the business pain' if i in (2, 3) else 'one clear sentence'}.  "
            f"<b>Transition:</b> <i>{trans}</i>", "small")

    # ===================================================================== 7
    b.h1("Complete Live Demo - Step by Step")
    b.callout("Before you start: app running at http://localhost:8501, role = Business Analyst, browser zoom 90%, this PDF open on a "
              "second screen. All expected outputs below are the recorded outputs of this exact build.", "tip")
    demo = [
        ("Open the PaymentLens dashboard", {"Screen": "Sidebar (role, OpenAI status, data as-of 2026-11-16 06:00) and eight example buttons.",
         "Do": "Nothing yet - point at the sidebar.", "Say": "This is PaymentLens. I'm signed in as a Business Analyst; the data is a synthetic four-week payments dataset.",
         "Feature": "Simulated roles, offline/AI mode indicator.", "If it fails": "Restart: .\\.venv\\Scripts\\python.exe -m streamlit run app.py; if the DB is missing run data\\generate_data.py."}),
        ("Ask why success rate dropped", {"Screen": "Question box.", "Do": "Click 'Why did success fall?' (or type it) → Analyse.",
         "Question": "Why did payment success rate fall last week?", "System does": f"Runs {len(M['queries'])} validated queries in well under a second.",
         "Say": "One plain-English question, like a leader would ask.", "If it fails": "Use screenshots 01-04 in docs/screenshots."}),
        ("Show how the question was interpreted", {"Screen": "'How I understood your question' panel.",
         "Explain": f"Metric with numerator/denominator; current {M['resolved']['current']} vs {M['resolved']['previous']}; ambiguities ('success' could be order-level, 'last week' could be 7 days) and the partial 16 Nov excluded.",
         "Say": "It doesn't hide guesses - every assumption is written down. Notice it noticed the last day is still loading.", "Feature": "Ambiguity handling, freshness check."}),
        ("Show the generated and validated SQL", {"Screen": "Evidence & SQL tab → expand Q3.", "Explain": "The compiled SQL and the guard checks table (all passed).",
         "Say": "The AI didn't write this SQL - our compiler did, from the metric dictionary, and the guard validated it before it ran.", "Feature": "Deterministic SQL, guard, audit."}),
        ("Display the metric comparison and chart", {"Screen": "KPI row + Trend tab.", "Explain": f"{P0} → {P1}, {DL}, p < 0.001, confidence Medium (with reasons).",
         "Say": "The drop is real, not noise - the significance test says so.", "Feature": "Statistics, confidence."}),
        ("Bank / payment-method segmentation", {"Screen": "Segments tab.", "Explain": "Per-bank and per-method tables with shares, rates and contributions.",
         "Say": "Here's every segment's share and success rate in both weeks.", "Feature": "Cohort comparison."}),
        ("Mix shift vs actual deterioration", {"Screen": "Root cause tab - waterfall.", "Explain": f"Previous {P0} → mix {MIX} → rate {RATE} → current {P1}; residual ~1e-17.",
         "Say": f"This is the key insight: about half the drop is traffic moving to Zenith Bank, which is always weaker; the other half is real deterioration. And they add up exactly.",
         "Feature": "Decomposition (signature feature)."}),
        ("Counterfactual analysis", {"Screen": "Counterfactual row under the waterfall.", "Explain": f"At last week's mix, this week's rate would be {CF} instead of {P1}.",
         "Say": "In plain words: if traffic had been routed like last week, we'd be at this number.", "Feature": "Counterfactual."}),
        ("Evidence and provenance", {"Screen": "Drill-down tab, then Evidence tab facts table.",
         "Explain": f"{DD['segment']}: {DD['top_reason']} {DD['reason_prev']} → {DD['reason_cur']}; bad days {', '.join(DD['bad_days'])}. Facts F1..F{len(M['facts'])} each cite query ids.",
         "Say": "Every sentence maps to a query. This is what lets an analyst trust it.", "Feature": "Drill-down, provenance."}),
        ("Data-quality exception (duplicates)", {"Screen": "Click 'Raw vs trusted data'.", "Question": "What was success rate last week using raw data?",
         "Explain": f"Raw {pct(IMP['raw_rate'])} vs trusted {pct(IMP['trusted_rate'])} ({IMP['difference_pp']:+.2f}pp) - caused by {GT['data_quality']['duplicate_extra_rows']} duplicated failed rows.",
         "Say": "If we trusted raw data we'd report a much worse number. PaymentLens shows the impact and uses the clean value.", "Feature": "DQ gate, two sources disagree."}),
        ("Restricted data access", {"Screen": "Click 'Merchant bank accounts'.", "Question": "Show individual merchants with their settlement bank account details",
         "Explain": esc(DEN["message"]) + " Plus what the role CAN see and a safe alternative.", "Say": "Access control happens before any SQL runs - and it doesn't rely on the AI.",
         "Feature": "RBAC.", "Optional": "Switch role to Regional Analyst (North), ask the main question again → scoped answer; Evidence tab shows the rewritten SQL."}),
        ("Recommendations and limitations", {"Screen": "Answer cards.", "Explain": "Hypotheses are labelled with confidence and evidence; recommendations are concrete checks.",
         "Say": "Note the wording: 'consistent with', not 'caused by'. The data shows contribution, not proof; the hypothesis says what extra data would confirm it.", "Feature": "Fact/hypothesis separation."}),
        ("Conclude with value", {"Screen": "Back to the top of the answer.", "Say": "In seconds we went from a question to a decomposed, data-checked, permission-checked answer with its evidence. That's what used to take an analyst hours.",
         "Optional extra": "Mix-shift week example (Simpson banner) or SQL Explorer 'Drop a table' → BLOCKED."}),
    ]
    for i, (t, rows) in enumerate(demo, 1):
        demo_step(b, i, t, rows)
    b.image(SHOT / "05_simpson.jpg", 0.85, "Backup screenshot: Simpson's-paradox week.")
    b.image(SHOT / "06_denied.jpg", 0.85, "Backup screenshot: access denied with what the role can see and a safe alternative.")

    # ===================================================================== 8
    b.h1("Demo Speaking Script")
    b.h2("30-second elevator pitch")
    b.callout(f"Every payments team asks: why did our success rate drop? Today an analyst spends hours to answer. PaymentLens answers in "
              f"seconds - and proves it. Ask in plain English; it builds safe SQL from agreed metric definitions, checks the data and "
              f"your permissions, and splits the change into what's real deterioration and what's just a traffic-mix shift. In our "
              f"demo, success fell {abs(OV['delta']) * 100:.2f} points: about half was traffic moving to a weaker bank, half was a UPI "
              f"outage at one bank. Every number links to its query. It's an AI analyst you can check.", "say", "30 seconds")
    b.h2("2-minute project introduction")
    b.callout("I chose the Enterprise AI Business Analyst challenge. The problem: leaders ask why payment success changed, and analysts spend hours "
              "finding data, writing queries and preparing explanations - and the answer can still use the wrong definition or dirty data.<br/><br/>"
              "I didn't want to build another chatbot that writes SQL. So in PaymentLens, the AI's only jobs are understanding the question and "
              "phrasing the answer. The question becomes a structured request using names from a metric dictionary. Our code compiles the SQL, "
              "a guard validates it, and it runs on a read-only database with a timeout, cache and audit log.<br/><br/>"
              f"Then the analysis: success fell from {P0} to {P1}. PaymentLens shows that {MIX} came from traffic shifting toward Zenith Bank, "
              f"which always performs lower, and {RATE} from genuine deterioration - mostly Nova Bank UPI, where issuer-unavailable failures jumped "
              f"from {DD['reason_prev']} to {DD['reason_cur']} on {DD['bad_days'][0]} to {DD['bad_days'][-1]}. It also warned me that the raw data has "
              f"{GT['data_quality']['duplicate_extra_rows']} duplicates and that the last day is still loading.<br/><br/>"
              "The answer is split into facts, hypotheses and recommended next steps, with confidence and the SQL behind every number. "
              "And it refuses what it shouldn't do - restricted data, unsafe queries, or questions the data can't answer.", "say", "2 minutes")
    b.h2("5-minute product demonstration")
    b.p("Follow section 7 steps 1-2-3-7-8-9-10-11-13 and use these lines:")
    b.bullets([
        "<b>(0:00)</b> 'This is PaymentLens, logged in as a Business Analyst on a synthetic four-week payments dataset.'",
        "<b>(0:20)</b> Click the main example. 'I just asked: why did payment success rate fall last week?'",
        "<b>(0:40)</b> Understanding panel. 'It tells me exactly what it understood and every assumption - including that the newest day is still loading, so it used the last complete week.'",
        f"<b>(1:20)</b> KPIs. '{P0} to {P1} - a {abs(OV['delta']) * 100:.2f}-point drop, statistically significant.'",
        f"<b>(1:50)</b> Root cause. 'Here's the key: {MIX} is mix shift - more traffic going to Zenith, which is always weaker - and {RATE} is real deterioration. They add up exactly. If the mix hadn't changed we'd be at {CF}.'",
        f"<b>(2:50)</b> Drill-down. 'The real deterioration is Nova Bank UPI - issuer-unavailable failures from {DD['reason_prev']} to {DD['reason_cur']}, concentrated on {DD['bad_days'][0]}-{DD['bad_days'][-1]}.'",
        "<b>(3:20)</b> Cards + Evidence. 'Facts, hypotheses with confidence, next steps - and every fact points to a query I can open.'",
        f"<b>(3:50)</b> Raw data example. 'Raw data would say {pct(IMP['raw_rate'])}; duplicates explain the gap; the trusted number is used.'",
        "<b>(4:20)</b> Restricted example. 'Ask for merchant bank accounts as an analyst - denied before any SQL runs, with a safe alternative.'",
        "<b>(4:45)</b> Close. 'Question to auditable answer in seconds. An AI analyst you can check.'"])
    b.h2("7-10 minute complete technical presentation")
    b.bullets([
        "<b>Problem (1 min):</b> slides 1-3 notes.",
        "<b>Design principle (1 min):</b> 'LLM is not the calculator, not the database authority, not the security layer.' Explain the closed-vocabulary AnalysisIntent and the two fallbacks.",
        "<b>Architecture (1.5 min):</b> walk the 12-step pipeline; stress the single governed query path: guard (13 AST checks), row-scope rewrite, read-only DuckDB with external access disabled, 5-second timeout, cache, audit log.",
        f"<b>Maths (1.5 min):</b> blended rate = weighted average; symmetric decomposition (rate + mix = total exactly, residual ~1e-17); counterfactual {CF}; z-test significance and minimum volume for drivers; Simpson detector (week of 26 Oct: total {pp(SD['delta'])} while segments improved {pp(SD['rate_effect'])}).",
        "<b>Live demo (3 min):</b> section 7 short path.",
        f"<b>Trust & testing (1 min):</b> ground truth computed independently by the generator; {N_TESTS} tests; known-answer questions 20/20 offline and {LL} with OpenAI (the live run first found three bugs, now fixed); 17 malicious SQL statements blocked; number-grounding check rejects invented numbers.",
        "<b>Limits & next steps (1 min):</b> synthetic data, simulated roles, small evaluation set, contribution not causation; next: warehouse connector, SSO, alerting, a larger AI evaluation set."])

    # ===================================================================== 9
    b.h1("Failure and Recovery Demonstration")
    b.h2("Recommended failure to show: duplicate records (data-quality)")
    b.table([["Item", "Detail"],
             ["Steps", "Click 'Raw vs trusted data' (or type: What was success rate last week using raw data?). Optionally run the main question and point to the yellow banner."],
             ["Expected result (recorded)", f"Answer {pct(RAW['analysis']['overall']['current']['value'])} on raw data with assumption 'Using RAW data as requested: duplicates and invalid rows are NOT removed', plus warning: raw {pct(IMP['raw_rate'])} vs trusted {pct(IMP['trusted_rate'])} ({IMP['difference_pp']:+.2f}pp), {GT['data_quality']['duplicate_extra_rows']} duplicate rows."],
             ["Why it occurs", "The synthetic generator replayed 500 FAILED events on 12-13 Nov (an 'ingestion replay'), so raw data double-counts failures."],
             ["How the app handles it", "The trusted view keeps the first ingested copy per txn_id; the DQ gate counts duplicates in the analysis window and computes the metric on both sources."],
             ["How to explain", "'The system didn't just warn - it showed that dirty data would have made the drop look about two points worse, and used the clean number.'"],
             ["If it doesn't appear", "Check the Data quality tab (count 500). If the database was regenerated, rerun data\\generate_data.py (seed 42 reproduces identical numbers). Fallback: screenshot 02_kpis_dq.jpg."]],
            [0.22, 0.78])
    b.h2("Alternative failure: access control")
    b.table([["Item", "Detail"],
             ["Steps", "Role Business Analyst → click 'Merchant bank accounts'."],
             ["Expected", esc(DEN["message"]) + " Lists allowed scope and suggests 'Show payment success rate by merchant for last week'."],
             ["Why", "settlement_account is a restricted column for this role in config/policies.yaml."],
             ["Handling", "policy.check_intent() denies before filter validation and before any analysis SQL; audit event 'DENIED'."],
             ["If it doesn't appear", "Make sure the role dropdown shows Business Analyst (Admin is allowed but gets 'not part of guided analysis')."]], [0.22, 0.78])
    b.h2("Other failures you can trigger")
    b.bullets([f"<b>Expensive query:</b> 'Show success rate for the last 120 days' → {esc(BUD['message'])}",
               "<b>Unsafe SQL:</b> SQL Explorer → 'Drop a table (unsafe)' → BLOCKED: Only SELECT queries are allowed (guard checks listed).",
               f"<b>Unanswerable question:</b> 'Did Zenith Bank intentionally reject our transactions?' → {esc(UNS['message'][:150])}...",
               "<b>Scope:</b> role Regional Analyst (North) → any question is limited to North; Evidence tab shows the rewritten SQL."])
    b.h2("Fallback plan for API or internet failure")
    b.bullets(["PaymentLens runs fully offline: with no key (or an API error) the rule-based parser and template narrative are used automatically, and the reason is shown under assumptions.",
               "Toggle 'Use OpenAI' off in the sidebar to force offline mode before the demo if the network is unreliable.",
               "If the laptop itself fails: present slides with the screenshots in docs/screenshots (01-07) and the charts in docs/evidence.",
               "If Streamlit fails: run scripts\\capture_evidence.py and show docs/evidence/main.json (SQL, facts, trace) in an editor."])
    b.callout("Agar internet ya API band ho jaaye to bhi demo chalega - app khud rule-based parser par shift ho jaata hai. Laptop hi "
              "band ho jaaye to screenshots aur slides se poora flow dikha do.", "hinglish")

    # ===================================================================== 10
    b.h1("Judges' Questions and Answers")
    QA = [
        ("What problem are you solving?", "Explaining why payment success changed - fast, correctly and with proof.",
         "Leaders' 'why' questions take analysts hours and are error-prone (definitions, dirty data, access). PaymentLens automates the analysis while keeping it auditable.", "PDF 2 §1"),
        ("Why did you choose this challenge?", "It can be built end to end on local data and shows real analytical reasoning.",
         "The mix-shift scenario requires maths, not just SQL, and every failure scenario in the brief can be demonstrated deterministically.", "PDF 2 §2"),
        ("Why use AI at all?", "To understand flexible human language and to write readable explanations.",
         "Those are the two tasks AI is good at. Calculations, SQL and permissions stay deterministic so answers are repeatable and testable.", "core/pipeline.py; ai/"),
        ("Why not basic text-to-SQL?", "A model can write a valid query for the wrong metric, run unsafe SQL or invent numbers.",
         "We use structured intent → compiled SQL from a semantic layer → AST guard → read-only engine. The SQL Explorer still allows free SQL but through the same guard.", "sqlengine/"),
        ("Which LLM do you use?", "OpenAI via the Responses API with Structured Outputs; model set in .env.",
         f"client.responses.parse(text_format=AnalysisIntent) returns a validated Pydantic object. Live-tested with {LLM_MODEL}: {LL} on the known-answer set, same numbers as offline mode.", "ai/llm_client.py; reports/eval_report_llm.json"),
        ("What happens if the LLM fails or hallucinates?", "We fall back to a rule-based parser; invented numbers are rejected.",
         "LLMUnavailable on any API/schema error → rule parser. The narrator's grounding check rejects any number or fact id not in the computed facts and shows the template instead.", "ai/narrator.py::grounding_check"),
        ("How is SQL generated?", "Our compiler builds it from metric definitions in YAML.",
         "compile_metric() assembles SELECT/JOIN/WHERE/GROUP BY from configured fragments; filter values are validated against the catalog and escaped.", "sqlengine/compiler.py"),
        ("How do you stop unsafe SQL?", "Three layers: AST guard, read-only engine, budget/timeout.",
         "sqlglot guard (single SELECT, no DDL/DML/COPY/ATTACH/PRAGMA, no file/system functions, allowed tables/columns, join conditions); DuckDB read_only, external access disabled, config locked; 5 s interrupt. 17 attacks blocked in tests.", "sqlengine/guard.py; tests/test_sql_guard.py"),
        ("Describe the database.", "Four tables plus a trusted view, all synthetic.",
         f"transactions_raw ({GT['row_counts']['transactions_raw']:,} rows) with planted anomalies; transactions view ({GT['row_counts']['transactions_trusted']:,}); merchants (100), banks (4), settlements ({GT['row_counts']['settlements']:,}).", "PDF 1 §6"),
        ("What exactly is 'success rate'?", "Successful attempts ÷ attempts that reached SUCCESS or FAILED.",
         "PENDING and USER_CANCELLED excluded; each retry is an attempt. Order conversion (net of retries) is a separate metric; the ambiguity is shown.", "config/metrics.yaml"),
        ("How does the root-cause analysis work?", "It splits the change into segment deterioration and traffic-mix shift.",
         f"Symmetric two-period decomposition over bank × payment method: Σ rate effects + Σ mix effects = total. Recorded: {RATE} + {MIX} = {DL}.", "analytics/decomposition.py"),
        ("Is the maths correct? How do you know?", "Yes - it reconciles exactly and matches independent ground truth.",
         "Residual ~1e-17; hand-checked unit tests; ground truth computed with pandas by the generator matches to 1e-12.", "tests/test_math.py; tests/test_ground_truth.py"),
        ("Why the symmetric method?", "It doesn't favour either week's weights.",
         "Using only previous or only current weights assigns the interaction term entirely to one effect; the symmetric version splits it 50/50 and still reconciles exactly. The counterfactual convention is shown alongside with the interaction term.", "PDF 1 §7"),
        ("What is the counterfactual?", "The rate we'd have if traffic mix hadn't changed.",
         f"Σ previous share × current rate = {CF} vs {P1} actual.", "decompose()"),
        ("Is the driver the cause?", "No - it's the largest contributor. We say 'consistent with', not 'caused by'.",
         "Contribution accounting is not causal inference; hypotheses carry confidence and say what extra data (e.g. issuer telemetry) would confirm them.", "analytics/insights.py"),
        ("How do you avoid flagging noise?", "Significance tests and minimum volume.",
         "Two-proportion z-test p < 0.05 and ≥ 200 attempts in both periods before a segment is 'significant'; the overall change also gets a p-value and confidence.", "analytics/stats.py"),
        ("What is Simpson's paradox here?", "The total falls while every segment improves - pure mix.",
         f"Week of 26 Oct: total {pp(SD['delta'])}, segments {pp(SD['rate_effect'])}, mix {pp(SD['mix_effect'])}; 15 of 16 segments improved. The detector flags it.", "simpson_check()"),
        ("How do you handle data quality?", "Six checks, run before trusting the answer, with numeric impact.",
         f"Freshness, duplicates, missing and orphan bank ids, invalid statuses, future timestamps; raw {pct(IMP['raw_rate'])} vs trusted {pct(IMP['trusted_rate'])}.", "analytics/data_quality.py"),
        ("Why keep transactions with a missing bank?", "They are real payments; dropping them would bias totals.",
         "They stay in totals and appear as bank 'UNKNOWN' in breakdowns, with a warning.", "metrics.yaml dimension 'bank'"),
        ("What if two sources disagree?", "We show both numbers and explain the gap.",
         f"Raw vs trusted (duplicates); transactions vs settlements: gap INR {RC['gap_amount']:,.2f} = pending + missing + mismatches, identity holds exactly.", "analytics/reconciliation.py"),
        ("How does access control work?", "Three enforcement points: intent check, restricted columns, row-scope rewrite.",
         "Restricted attributes → DENIED before any SQL; guard blocks restricted columns and SELECT * on merchants; scoped roles get every table rewritten into a filtered subquery.", "security/policy.py"),
        ("Can a prompt trick the AI into leaking data?", "No - security does not depend on the AI.",
         "Sensitive-attribute detection is deterministic and merged into every intent; even crafted SQL still passes the guard and row-scope rewrite. Tested: an LLM output that omits the attribute is still denied.", "tests/test_ai_layer.py"),
        ("How do you handle ambiguous questions?", "Pick a sensible default, say so, and lower confidence.",
         "Ambiguities (denominator, 'last week') and assumptions (exact dates, partial day) are listed; each ambiguity reduces the confidence score.", "core/time_resolver.py; insights.confidence"),
        ("What about expensive queries?", "Budget limits before SQL; join limits in the guard; timeout during execution.",
         "> 90 days or > 3 dimensions → BLOCKED; cartesian joins or > 4 joins blocked; 5 s interrupt; results cached by data version + SQL.", "config/metrics.yaml limits"),
        ("How did you test it?", f"{N_TESTS} automated tests and a 20-question known-answer evaluation, offline and with OpenAI.",
         f"Maths, SQL safety, RBAC, ground truth, AI fallbacks and AI regressions; evaluation {EVAL['summary']['cases_passed']}/{EVAL['summary']['cases_total']} offline and {LL} with OpenAI. The first live run scored 15/20 and found three integration bugs, which we fixed - that is exactly why we evaluate.", "tests/; scripts/run_eval.py"),
        ("What is novel here?", "The combination: decomposition + significance + data-quality impact + governance + grounded AI, in one auditable flow.",
         "Most demos stop at 'question → SQL → chart'. PaymentLens explains why, proves it, and knows when to refuse.", "PDF 2 §5"),
        ("How does it scale?", "The design scales; the demo engine is local.",
         "Swap DuckDB for a warehouse connector (same compiler/guard concept), move cache and audit to shared services, and add query cost estimation from the warehouse.", "-"),
        ("What are the production limitations?", "Synthetic data, simulated roles, local engine, limited parser coverage offline.",
         "No SSO, no real bank/provider integration, heuristic cost control, metric definitions need business sign-off, contribution not causation.", "README; PDF 2 §11"),
        ("How do you handle errors?", "Nothing crashes the UI; every failure has a status and a message.",
         "QueryBlocked → BLOCKED; QueryError/timeouts → ERROR; unknown filter / bad dates → UNSUPPORTED; LLM errors → fallback with a note.", "core/pipeline.py::run"),
        ("Why Streamlit and DuckDB?", "Fastest way to build a serious, interactive data app in 48 hours.",
         "DuckDB is embedded, fast, supports read-only and disabling external access; Streamlit is pure Python with interactive Plotly charts.", "PDF 1 §1.4"),
        ("How confident is the system in its answer?", "It gives a score and the reasons.",
         f"Main question: {M['confidence']['level']} ({M['confidence']['score']}/100) - reduced for offline parser, ambiguities and handled data-quality warnings.", "insights.confidence"),
        ("What would you build next?", "Warehouse connector, SSO roles, proactive alerts, LLM evaluation at scale.",
         "Also more metrics (refund, chargeback), cohort comparisons over months, and a feedback loop where analysts confirm hypotheses.", "PDF 2 §11"),
    ]
    for i, (q, s, d, r) in enumerate(QA, 1):
        qa(b, i, q, s, d, r)

    # ===================================================================== 11
    b.h1("What We Actually Built")
    b.table([["Category", "Items"],
             ["Completed features " + tag("implemented"), "Rule-based question understanding; semantic layer; deterministic SQL compiler; SQL guard; read-only DuckDB executor with timeout and cache; governed query service; audit log; summary/trend/breakdown/root-cause/reconciliation analyses; decomposition, counterfactual, significance, Simpson detector, drill-down; data-quality gate with impact; facts/hypotheses/recommendations; confidence score; Streamlit UI with evidence and trace; SQL Explorer; known-answer evaluation; evidence capture; these PDFs."],
             ["Working integrations", f"DuckDB, sqlglot, Pydantic, Streamlit, Plotly, OpenAI Responses API ({LLM_MODEL}, live-tested)."],
             ["Mocked / simulated " + tag("mocked"), "All data (synthetic, seed 42, planted scenarios); roles (dropdown, no authentication); 'as-of' time fixed at 2026-11-16 06:00."],
             ["Verified results", f"{N_TESTS}/{N_TESTS} tests pass; evaluation {EVAL['summary']['cases_passed']}/{EVAL['summary']['cases_total']} offline and {LL} with OpenAI; AI narrative passed the number-grounding check; root-cause numbers match ground truth to 1e-12; app click-tested in a browser."],
             ["Tested failure scenarios", "Duplicates, missing bank ids, invalid statuses, future timestamps, partial day, raw vs trusted, settlements gap, restricted data, row scope, 17 unsafe SQL statements, 120-day budget, unknown bank, unanswerable question, LLM error fallback, LLM hallucinated numbers (mocked)."],
             ["Planned " + tag("planned"), "Larger AI evaluation set; SSO/identity provider; warehouse connectors; alerts; multimodal input; forecasting; deployment."],
             ["Known limitations", "Offline parser coverage; contribution ≠ causation; mix/rate split depends on segmentation; order attribution convention; single-process cache; simulated roles."]],
            [0.24, 0.76])

    # ===================================================================== 12
    b.h1("Final Presentation and Demo Checklist")
    checklist = [
        ("Environment", ["Python 3.11+ installed", ".venv created and requirements installed", "Laptop charged, notifications off, browser zoom 90%"]),
        ("Startup", ["data\\generate_data.py run (data/paymentlens.duckdb exists)", "streamlit run app.py opens at http://localhost:8501", "Role = Business Analyst"]),
        ("Required files", ["config/metrics.yaml, config/policies.yaml", "data/ground_truth.json", "docs/screenshots 01-07, docs/evidence charts"]),
        ("Data availability", ["Sidebar shows data as-of 2026-11-16 06:00:00", "Main question returns " + DL]),
        ("API credentials (optional)", [".env with OPENAI_API_KEY and OPENAI_MODEL", "Sidebar shows 'OpenAI connected' - or toggle off for offline demo", "Never show .env on screen"]),
        ("Working demo questions", [f"Why did payment success rate fall last week? ({DL})", "Why did success rate fall in the week of Oct 26 compared with the week before? (Simpson)",
                                    "What was success rate last week using raw data?", "Show individual merchants with their settlement bank account details (DENIED)"]),
        ("Test results", [f"pytest → {N_TESTS} passed", "scripts\\run_eval.py → 20/20", f"scripts\\run_eval.py --llm → {LL}"]),
        ("Backup", ["Screenshots ready in slides", "This PDF open", "docs/evidence/main.json available"]),
        ("Presentation", ["10 slides", "30-s, 2-min, 5-min scripts rehearsed", "Know the 5 key numbers (cheat sheet)"]),
        ("Expected judge questions", ["Why not text-to-SQL", "Hallucination", "Maths correctness", "Security", "Limitations"]),
    ]
    rows = [["Area", "Check", "Done"]]
    for area, items in checklist:
        for it in items:
            rows.append([area, esc(it), "[  ]"])
    b.table(rows, [0.22, 0.68, 0.1])

    # ===================================================================== 13
    b.h1("One-Page Revision Cheat Sheet")
    b.table([["Topic", "Remember this"],
             ["Problem", "Leaders ask why payment success changed; analysts take hours; answers risk wrong definitions, dirty data, leaks, guesses."],
             ["Solution", "PaymentLens: AI understands + explains; Python/SQL calculate; every number has evidence."],
             ["Architecture", "UI → freshness → intent (AI/rules) → policy → filters → dates → budget → compiler → guard → row scope → DuckDB read-only → analysis → DQ → facts → narrative → confidence."],
             ["Important files", "core/pipeline.py, ai/intent_parser.py, sqlengine/{compiler,guard,service}.py, analytics/{decomposition,data_quality}.py, security/policy.py, config/metrics.yaml, app.py"],
             ["AI components", "Intent parser (OpenAI Structured Outputs → AnalysisIntent) and narrator (number-grounded); both fall back offline."],
             ["Analysis methods", "Symmetric mix/rate decomposition; counterfactual Σ w_prev·r_curr; z-test + Wilson CI; Simpson detector; drill-down by decline reason and day."],
             ["Key numbers", f"{P0} → {P1} ({DL}); mix {MIX}; rate {RATE}; counterfactual {CF}; Nova UPI {pct(NU['r0'])} → {pct(NU['r1'])}; ISSUER_UNAVAILABLE {DD['reason_prev']} → {DD['reason_cur']}; raw {pct(IMP['raw_rate'])}; Simpson week {pp(SD['delta'])} with segments {pp(SD['rate_effect'])}."],
             ["Differentiators", "Decomposition + counterfactual; Simpson detector; DQ impact; governed SQL; RBAC with SQL rewrite; facts vs hypotheses; grounded AI text; independent ground truth."],
             ["Demo order", "Main question → understanding → SQL → KPIs → segments → waterfall → counterfactual → drill-down/evidence → raw data → denied → recommendations → close."],
             ["Key limitations", f"Synthetic data; simulated roles; small evaluation set (20 questions, {LL} with OpenAI); contribution ≠ causation."],
             ["Final pitch", "\"We didn't build another text-to-SQL chatbot. We built an AI analyst you can check.\""]], [0.18, 0.82], font=8.4)
    b.callout("Yaad rakho: AI samajhta hai aur likhta hai, maths code karta hai, permission policy decide karti hai, aur har number ka "
              "saboot Evidence tab mein hai.", "hinglish")
    b.build()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
