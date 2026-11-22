"""Exports the walkthrough slides as HTML and PNG files."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from playwright.sync_api import sync_playwright  # noqa: E402

from record_demo import slide  # noqa: E402

OUT = ROOT / "docs" / "video" / "slides"

SLIDES = {
    "01_title": "<h1>An AI analyst for payment performance that shows its evidence</h1>"
                "<p class='lead'>Challenge 2: Enterprise AI Business Analyst. A solo build with synthetic payments data.</p>",
    "02_problem": "<h2>Why did payment success rate drop?</h2><ul>"
                  "<li>Leaders ask this every week. Analysts need <b>hours</b> to find data, write SQL and explain it.</li>"
                  "<li>A dashboard shows <b>what</b> changed, not <b>why</b>.</li>"
                  "<li>Basic text-to-SQL can pick the wrong denominator, run unsafe SQL, miss dirty data, or invent numbers.</li></ul>",
    "03_solution": "<h2>How PaymentLens answers</h2><div class='flow'>"
                   "<span class='ai'>Question → structured intent (AI)</span><em>→</em>"
                   "<span>Access check</span><em>→</em><span>SQL from metric definitions</span><em>→</em>"
                   "<span>Safety guard + read-only DuckDB</span><em>→</em><span>Mix vs rate decomposition</span><em>→</em>"
                   "<span>Data-quality checks</span><em>→</em><span class='ai'>Facts, explanations, next steps (AI wording, number-checked)</span>"
                   "</div><p class='note'>The AI reads the question and words the answer. Python and SQL do all the maths.</p>",
    "04_closing": "<h2>What you saw</h2><ul>"
                  "<li>A plain-English question answered with <b>SQL, maths and evidence</b></li>"
                  "<li>Mix shift separated from real deterioration, with a counterfactual</li>"
                  "<li>Data-quality checks and access control before any answer</li>"
                  "<li>48 automated tests; 20 of 20 known-answer questions, offline and with OpenAI</li></ul>"
                  "<p class='note'>Limits: synthetic data, simulated roles, and driver analysis shows contribution, not proven cause.</p>",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for name, inner in SLIDES.items():
            html = slide(inner)
            (OUT / f"{name}.html").write_text(html, encoding="utf-8")
            page.set_content(html)
            page.wait_for_timeout(1200)   # let the web font load
            page.screenshot(path=str(OUT / f"{name}.png"))
        browser.close()
    print(f"Slides written to {OUT}")


if __name__ == "__main__":
    main()
