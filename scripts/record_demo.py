"""Records a captioned walkthrough video of the app with Playwright."""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "video"
PORT = 8502
URL = f"http://localhost:{PORT}"
W, H = 1440, 900
PY = sys.executable

CAPTION_JS = """(text) => {
  let el = document.getElementById('pl-cap');
  if (!el) {
    el = document.createElement('div'); el.id = 'pl-cap'; document.body.appendChild(el);
    Object.assign(el.style, {position:'fixed', left:'50%', bottom:'26px', transform:'translateX(-50%)', maxWidth:'1040px',
      width:'max-content', zIndex:'2147483647', background:'rgba(19,32,58,.88)', color:'#fff',
      font:'500 19px/1.45 Geist, "Segoe UI", system-ui, sans-serif', padding:'12px 22px', borderRadius:'12px',
      boxShadow:'0 12px 32px -12px rgba(0,0,0,.5)', textAlign:'center', transition:'opacity .25s', pointerEvents:'none'});
  }
  el.textContent = text; el.style.opacity = text ? '1' : '0';
}"""

SLIDE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&display=swap');
html,body{margin:0;height:100%;font-family:Geist,'Segoe UI',system-ui,sans-serif;color:#13203A;background:#EAEFF5;}
body{display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;}
body::before{content:"";position:fixed;inset:0;background:
 radial-gradient(48rem 34rem at 8% -8%,rgba(14,124,116,.20),transparent 70%),
 radial-gradient(42rem 32rem at 96% 6%,rgba(70,92,190,.15),transparent 70%),
 radial-gradient(52rem 34rem at 55% 112%,rgba(14,124,116,.11),transparent 70%);}
.card{position:relative;width:1040px;padding:56px 64px;border-radius:22px;background:rgba(255,255,255,.66);
 backdrop-filter:blur(18px);border:1px solid rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(19,32,58,.05),0 24px 60px -28px rgba(19,32,58,.35);}
.brand{display:flex;align-items:center;gap:12px;font-weight:650;font-size:22px;color:#13203A;margin-bottom:34px;}
.brand i{width:14px;height:14px;border-radius:4px;background:#0E7C74;display:inline-block;}
h1{font-size:52px;line-height:1.08;letter-spacing:-.03em;margin:0 0 18px;font-weight:640;}
h2{font-size:38px;line-height:1.15;letter-spacing:-.025em;margin:0 0 26px;font-weight:620;}
p.lead{font-size:22px;color:#56667D;margin:0;max-width:56ch;line-height:1.5;}
ul{margin:0;padding-left:26px;font-size:23px;line-height:1.55;} li{margin-bottom:10px;} li b{font-weight:620;}
.flow{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:18px;margin-top:6px;}
.flow span{background:rgba(255,255,255,.85);border:1px solid rgba(19,32,58,.12);border-radius:10px;padding:9px 14px;}
.flow span.ai{border-color:rgba(14,124,116,.55);color:#0A5F59;font-weight:600;}
.flow em{color:#56667D;font-style:normal;}
.note{margin-top:26px;font-size:19px;color:#56667D;}
"""


def slide(inner: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{SLIDE_CSS}</style></head><body>" \
           f"<div class='card'><div class='brand'><i></i>PaymentLens</div>{inner}</div></body></html>"


class Recorder:
    def __init__(self, page):
        self.page = page
        self.t0 = time.monotonic()
        self.cues: list[tuple[float, float, str, str]] = []
        self._cur: tuple[float, str, str] | None = None

    def now(self) -> float:
        return time.monotonic() - self.t0

    def say(self, text: str, screen: str, hold: float = 0.0):
        self._close()
        self._cur = (self.now(), text, screen)
        try:
            self.page.evaluate(CAPTION_JS, text)
        except Exception:
            pass
        if hold:
            time.sleep(hold)

    def refresh_caption(self):
        if self._cur:
            try:
                self.page.evaluate(CAPTION_JS, self._cur[1])
            except Exception:
                pass

    def _close(self):
        if self._cur:
            s, t, sc = self._cur
            if t:
                self.cues.append((s, self.now(), t, sc))
            self._cur = None

    def finish(self):
        self._close()


def ts(sec: float, sep: str = ",") -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def wait_for_server(timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(URL, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Streamlit did not start on port 8502")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir = OUT / "_raw"
    shutil.rmtree(raw_dir, ignore_errors=True)
    server = subprocess.Popen([PY, "-m", "streamlit", "run", "app.py", "--server.port", str(PORT), "--server.headless", "true",
                               "--client.toolbarMode", "viewer", "--browser.gatherUsageStats", "false"],
                              cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_server()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(raw_dir),
                                      record_video_size={"width": W, "height": H})
            page = ctx.new_page()
            rec = Recorder(page)
            try:
                run_story(page, rec)
            finally:
                rec.finish()
                page.screenshot(path=str(OUT / "_last_frame.png"))
                video = page.video.path()
                ctx.close()
                browser.close()
    finally:
        server.terminate()

    mp4 = OUT / "PaymentLens_Walkthrough.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium", "-movflags", "+faststart", str(mp4)], check=True)
    shutil.rmtree(raw_dir, ignore_errors=True)

    srt = "\n".join(f"{i}\n{ts(s)} --> {ts(e)}\n{t}\n" for i, (s, e, t, _) in enumerate(rec.cues, 1))
    (OUT / "PaymentLens_Walkthrough.srt").write_text(srt, encoding="utf-8")
    rows = "\n".join(f"| {ts(s, '.')[3:8]} - {ts(e, '.')[3:8]} | {sc} | {t} |" for s, e, t, sc in rec.cues)
    total = rec.cues[-1][1] if rec.cues else 0
    (OUT / "PaymentLens_Walkthrough_script.md").write_text(
        f"# PaymentLens walkthrough - narration script\n\nTotal length about {int(total // 60)} min {int(total % 60)} s. "
        "Read each line while the matching screen is shown. Timings come from the recording.\n\n"
        "| Time | On screen | What to say |\n|---|---|---|\n" + rows + "\n", encoding="utf-8")
    print(f"Video: {mp4}  ({total:.0f} s, {len(rec.cues)} scenes)")


# ----------------------------------------------------------------------------- the story
def dismiss_popups(page) -> None:
    try:
        b = page.get_by_role("button", name="Close")
        if b.count() and b.first.is_visible():
            b.first.click()
    except Exception:
        pass


def click_example(page, name: str) -> None:
    page.get_by_role("button", name=name).click()
    page.mouse.move(80, 860)   # move away so the button's help tooltip does not stay on screen


def glide_to(page, locator, block: str = "start", pause: float = 1.3) -> None:
    locator.first.evaluate(f"e => e.scrollIntoView({{behavior: 'smooth', block: '{block}'}})")
    time.sleep(pause)


def run_story(page, rec: Recorder) -> None:
    # --- 1. title, problem, solution (slides) ---------------------------------------------
    page.set_content(slide("<h1>An AI analyst for payment performance that shows its evidence</h1>"
                           "<p class='lead'>Challenge 2: Enterprise AI Business Analyst. A solo build with synthetic payments data.</p>"))
    time.sleep(1.2)
    rec.say("Hi, this is PaymentLens: an AI analyst that explains why payment success changed, and shows the proof for every number.",
            "Title slide", 7)
    page.set_content(slide("<h2>Why did payment success rate drop?</h2><ul>"
                           "<li>Leaders ask this every week. Analysts need <b>hours</b> to find data, write SQL and explain it.</li>"
                           "<li>A dashboard shows <b>what</b> changed, not <b>why</b>.</li>"
                           "<li>Basic text-to-SQL can pick the wrong denominator, run unsafe SQL, miss dirty data, or invent numbers.</li></ul>"))
    rec.say("The problem: leaders ask why success rate dropped. Dashboards show what changed, not why, and a basic text-to-SQL "
            "chatbot can use the wrong definition, dirty data, or invent numbers.", "Problem slide", 10)
    page.set_content(slide("<h2>How PaymentLens answers</h2><div class='flow'>"
                           "<span class='ai'>Question → structured intent (AI)</span><em>→</em>"
                           "<span>Access check</span><em>→</em><span>SQL from metric definitions</span><em>→</em>"
                           "<span>Safety guard + read-only DuckDB</span><em>→</em><span>Mix vs rate decomposition</span><em>→</em>"
                           "<span>Data-quality checks</span><em>→</em><span class='ai'>Facts, explanations, next steps (AI wording, number-checked)</span>"
                           "</div><p class='note'>The AI reads the question and words the answer. Python and SQL do all the maths.</p>"))
    rec.say("PaymentLens uses AI only to understand the question and to word the answer. The SQL, the maths, the data checks "
            "and the access rules are all deterministic code.", "Solution slide", 10)

    # --- 2. the app --------------------------------------------------------------------
    page.goto(URL)
    page.get_by_text("Ask a question about payment performance").wait_for(timeout=60000)
    time.sleep(2)
    dismiss_popups(page)
    sidebar = page.locator('[data-testid="stSidebar"]')
    toggle = sidebar.locator('input[type="checkbox"]').first
    if toggle.is_checked():
        sidebar.get_by_text("Use OpenAI for understanding").click()
        time.sleep(1.5)
    assert not toggle.is_checked(), "OpenAI toggle is still on"
    rec.say("This is the app. I'm signed in as a Business Analyst. For this recording the OpenAI toggle is off so answers are "
            "instant; with it on, the numbers are identical.", "App home, sidebar with role and OpenAI toggle", 7)

    box = page.get_by_placeholder("e.g. Why did payment success rate fall last week?")
    box.click()
    rec.say("I ask the question a leader would ask.", "Typing into the question box", 0)
    box.press_sequentially("Why did payment success rate fall last week?", delay=45)
    time.sleep(0.6)
    page.get_by_role("button", name="Analyse").click()
    page.get_by_text("What the data shows").wait_for(timeout=60000)
    time.sleep(1)
    rec.refresh_caption()

    glide_to(page, page.get_by_text("How I understood your question"))
    rec.say("First it shows how it understood me: the metric with its exact definition, the two weeks compared, and every "
            "assumption. It even noticed 16 November is still loading and left it out.", "How I understood your question panel", 10)

    glide_to(page, page.get_by_text("Is the change real?"), block="center")
    rec.say("Success rate fell from 90.38% to 87.35%, down 3.03 points, and the change is statistically significant.",
            "Metric cards", 7)

    glide_to(page, page.get_by_text("Data-quality warnings"), block="center")
    rec.say("Before trusting that number it checks the data: 500 duplicate rows in the raw data would have shown 85.43% "
            "instead of 87.35%. It uses the clean figure and tells you.", "Data-quality warning box", 9)

    glide_to(page, page.get_by_text("What the data shows"), block="center")
    rec.say("The answer is split into facts, possible explanations with a confidence level, and recommended next steps.",
            "Answer cards", 8)

    glide_to(page, page.get_by_text("Change decomposed"), block="start", pause=0.6)
    page.mouse.move(80, 860)
    time.sleep(0.8)
    rec.say("This is the key insight. 1.58 points of the drop came from traffic shifting to Zenith Bank, which always "
            "performs lower. 1.45 points is real deterioration. Together they add up exactly.", "Root cause tab: waterfall and contributors", 11)

    glide_to(page, page.get_by_text("Counterfactual: what if the traffic mix had not changed?"), block="center")
    rec.say("If the traffic mix had stayed like last week, the rate would have been 88.80% instead of 87.35%.",
            "Counterfactual row", 7)

    page.get_by_role("tab", name="Drill-down").click()
    time.sleep(1)
    glide_to(page, page.get_by_text("Automatic drill-down"), block="start", pause=0.8)
    page.mouse.move(80, 860)
    rec.say("It then drills into the real problem automatically: Nova Bank UPI, where issuer-unavailable failures jumped "
            "from 18 to 301, concentrated on 11 to 14 November.", "Drill-down tab: decline reasons and daily rate", 10)

    page.get_by_role("tab", name="Evidence & SQL").click()
    time.sleep(1)
    q3 = page.get_by_text("Q3 ·")
    glide_to(page, q3, block="center", pause=0.8)
    q3.first.click()
    time.sleep(1)
    rec.say("Every fact links to the query that produced it. Our code compiled this SQL from the metric definitions, and a "
            "safety guard checked it before it ran on a read-only database.", "Evidence & SQL tab with query Q3 open", 10)

    # --- 3. Simpson's paradox ------------------------------------------------------------
    glide_to(page, page.get_by_text("Ask a question about payment performance"), pause=1.0)
    click_example(page, "Mix-shift week (Oct 26)")
    banner = page.get_by_text("Simpson's paradox detected")
    banner.wait_for(state="attached", timeout=60000)
    time.sleep(1)
    page.get_by_role("tab", name="Root cause").click()   # the previous scene left the Evidence tab selected
    banner.wait_for(timeout=15000)
    rec.say("A different week: here every bank and payment method improved, yet the total fell.", "Mix-shift week example", 0)
    glide_to(page, page.get_by_text("Change decomposed"), block="start", pause=0.6)
    page.mouse.move(80, 860)
    time.sleep(4)
    glide_to(page, banner, block="center")
    rec.say("PaymentLens flags this as Simpson's paradox: the whole drop is a traffic-mix effect, not a performance problem.",
            "Simpson's paradox banner", 8)

    # --- 4. access control ---------------------------------------------------------------
    glide_to(page, page.get_by_text("Ask a question about payment performance"), pause=1.0)
    click_example(page, "Merchant bank accounts")
    page.get_by_text("Access denied.").wait_for(timeout=60000)
    time.sleep(1)
    rec.say("Now I ask for merchant bank account details as an analyst. It is refused before any SQL runs, and it suggests "
            "a safe alternative.", "Access denied with allowed scope", 9)

    sel = sidebar.locator('[data-testid="stSelectbox"]')
    if sel.count():
        sel.first.click()
    else:
        page.mouse.click(150, 214)   # role dropdown position in the 1440x900 layout
    time.sleep(0.8)
    page.get_by_role("option", name="Regional Analyst (North only)").click()
    page.mouse.move(80, 860)
    time.sleep(2)
    click_example(page, "Why did success fall?")
    page.get_by_text("What the data shows").wait_for(timeout=60000)
    time.sleep(1)
    glide_to(page, page.get_by_text("limited to region = North"), block="center")
    rec.say("Switch to a regional analyst and ask again: the same analysis, limited to the North region. Every table is "
            "rewritten with a region filter, whatever SQL runs.", "Regional analyst: scoped answer", 10)

    # --- 5. SQL guard --------------------------------------------------------------------
    page.get_by_role("tab", name="SQL Explorer").click()
    time.sleep(1.2)
    page.get_by_role("button", name="Drop a table (unsafe)").click()
    time.sleep(1.2)
    page.get_by_role("button", name="Validate & run").click()
    page.get_by_text("Guard checks").wait_for(timeout=60000)
    time.sleep(0.8)
    rec.say("Free SQL is allowed too, but through the same guard. Dropping a table is blocked, with the reason and every "
            "check listed. Every decision is also saved in an audit log.", "SQL Explorer: DROP TABLE blocked", 10)

    # --- 6. close ------------------------------------------------------------------------
    page.set_content(slide("<h2>What you saw</h2><ul>"
                           "<li>A plain-English question answered with <b>SQL, maths and evidence</b></li>"
                           "<li>Mix shift separated from real deterioration, with a counterfactual</li>"
                           "<li>Data-quality checks and access control before any answer</li>"
                           "<li>48 automated tests; 20 of 20 known-answer questions, offline and with OpenAI</li></ul>"
                           "<p class='note'>Limits: synthetic data, simulated roles, and driver analysis shows contribution, not proven cause.</p>"))
    rec.say("So: a plain-English question, answered with SQL, maths and evidence, and the system knows when to refuse. "
            "PaymentLens: an AI analyst you can check. Thank you.", "Closing slide", 9)
    rec.say("", "End", 1)


if __name__ == "__main__":
    main()
