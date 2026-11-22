"""Shared reportlab helpers for building the documentation PDFs."""
from __future__ import annotations

import ast
import json
import math
import textwrap
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "docs" / "evidence"
FONTS = Path("C:/Windows/Fonts")

pdfmetrics.registerFont(TTFont("Arial", str(FONTS / "arial.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Bold", str(FONTS / "arialbd.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Italic", str(FONTS / "ariali.ttf")))
pdfmetrics.registerFont(TTFont("Arial-BoldItalic", str(FONTS / "arialbi.ttf")))
pdfmetrics.registerFont(TTFont("Consolas", str(FONTS / "consola.ttf")))
pdfmetrics.registerFont(TTFont("Consolas-Bold", str(FONTS / "consolab.ttf")))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic", boldItalic="Arial-BoldItalic")
pdfmetrics.registerFontFamily("Consolas", normal="Consolas", bold="Consolas-Bold", italic="Consolas", boldItalic="Consolas-Bold")

C = {
    "ink": colors.HexColor("#1b1b1a"), "muted": colors.HexColor("#52514e"), "blue": colors.HexColor("#2a78d6"),
    "navy": colors.HexColor("#0d366b"), "line": colors.HexColor("#d9d8d3"), "code": colors.HexColor("#f5f5f2"),
    "zebra": colors.HexColor("#f7f8fa"), "head": colors.HexColor("#1c5cab"), "green": colors.HexColor("#0a7a0a"),
    "orange": colors.HexColor("#c25220"), "red": colors.HexColor("#c53030"), "amber": colors.HexColor("#9a6700"),
    "ai": colors.HexColor("#fde6d8"), "det": colors.HexColor("#dbe9fb"), "sec": colors.HexColor("#fbdede"),
    "data": colors.HexColor("#ecebe7"), "ok": colors.HexColor("#ddf2dd"),
}
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

S = {
    "body": ParagraphStyle("body", fontName="Arial", fontSize=9.6, leading=14, textColor=C["ink"], spaceAfter=5),
    "small": ParagraphStyle("small", fontName="Arial", fontSize=8.4, leading=11.5, textColor=C["muted"], spaceAfter=4),
    "h1": ParagraphStyle("h1", fontName="Arial-Bold", fontSize=18, leading=23, textColor=C["navy"], spaceBefore=2, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName="Arial-Bold", fontSize=12.6, leading=17, textColor=C["head"], spaceBefore=10, spaceAfter=5),
    "h3": ParagraphStyle("h3", fontName="Arial-Bold", fontSize=10.4, leading=14, textColor=C["ink"], spaceBefore=7, spaceAfter=3),
    "bullet": ParagraphStyle("bullet", fontName="Arial", fontSize=9.6, leading=13.6, leftIndent=14, bulletIndent=4, spaceAfter=2.5, textColor=C["ink"]),
    "code": ParagraphStyle("code", fontName="Consolas", fontSize=7.5, leading=9.4, textColor=C["ink"]),
    "cell": ParagraphStyle("cell", fontName="Arial", fontSize=8.2, leading=10.6, textColor=C["ink"]),
    "cellcode": ParagraphStyle("cellcode", fontName="Consolas", fontSize=7.4, leading=9.4, textColor=C["ink"]),
    "cellhead": ParagraphStyle("cellhead", fontName="Arial-Bold", fontSize=8.2, leading=10.6, textColor=colors.white),
    "caption": ParagraphStyle("caption", fontName="Arial-Italic", fontSize=8, leading=10.5, textColor=C["muted"], alignment=TA_CENTER, spaceAfter=8),
    "callout": ParagraphStyle("callout", fontName="Arial", fontSize=9.2, leading=13.2, textColor=C["ink"]),
    "toc0": ParagraphStyle("toc0", fontName="Arial-Bold", fontSize=10, leading=15, leftIndent=0, textColor=C["navy"]),
    "toc1": ParagraphStyle("toc1", fontName="Arial", fontSize=8.8, leading=12, leftIndent=14, textColor=C["ink"]),
}

STATUS_TAG = {
    "implemented": ("IMPLEMENTED & VERIFIED", "#0a7a0a"),
    "untested": ("IMPLEMENTED - NOT RUN LIVE", "#c25220"),
    "partial": ("PARTIAL", "#9a6700"),
    "mocked": ("SIMULATED / MOCKED", "#6250d6"),
    "planned": ("PLANNED - NOT BUILT", "#c53030"),
}
STATUS_MEANING = {
    "implemented": "exists in the code and was executed / tested during this build",
    "untested": "code exists but was not executed against the real external service",
    "partial": "works for the documented cases, with known gaps",
    "mocked": "deliberately simulated (synthetic data, simulated roles)",
    "planned": "proposed future work; no code exists",
}


def esc(s) -> str:
    return escape(str(s))


def tag(kind: str) -> str:
    label, col = STATUS_TAG[kind]
    return f'<font name="Arial-Bold" size="7.4" color="{col}">[{label}]</font>'


def ev(name: str) -> dict:
    return json.loads((EVID / f"{name}.json").read_text(encoding="utf-8"))


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def pp(x: float) -> str:
    return f"{x * 100:+.2f}pp"


# ----------------------------------------------------------------------------- source extraction
def source_of(rel: str, name: str) -> tuple[str, int, int]:
    """Returns the exact source code of a function or class, with its first and last line numbers."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            start = node.lineno - len(node.decorator_list)
            return "\n".join(text.splitlines()[start - 1: node.end_lineno]), start, node.end_lineno
    raise KeyError(f"{name} not found in {rel}")


def signature_list(rel: str) -> list[tuple[str, str, int]]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out = []

    def sig(fn):
        args = [a.arg for a in fn.args.args]
        if fn.args.vararg:
            args.append("*" + fn.args.vararg.arg)
        if fn.args.kwonlyargs:
            if not fn.args.vararg:
                args.append("*")
            args += [a.arg for a in fn.args.kwonlyargs]
        ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
        return f"{fn.name}({', '.join(args)}){ret}"
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(("def", sig(node), node.lineno))
        elif isinstance(node, ast.ClassDef):
            out.append(("class", node.name, node.lineno))
            for b in node.body:
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(("method", f"{node.name}.{sig(b)}", b.lineno))
    return out


PKGS = {"core", "ai", "analytics", "sqlengine", "security", "scripts"}


def project_imports(rel: str) -> list[str]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] in PKGS:
            if n.module in PKGS:
                mods.update(f"{n.module}.{a.name}" for a in n.names)
            else:
                mods.add(n.module)
    return sorted(mods)


def module_name(rel: str) -> str:
    return rel.replace("/", ".").removesuffix(".py")


def callers(rel: str, files: list[str]) -> list[str]:
    m = module_name(rel)
    return sorted(f for f in files if f != rel and m in project_imports(f))


# ----------------------------------------------------------------------------- document
class _Doc(BaseDocTemplate):
    def __init__(self, path, title, short, cover_fn):
        super().__init__(str(path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=20 * mm,
                         bottomMargin=17 * mm, title=title, author="PaymentLens project", subject=title)
        self.short = short
        frame = Frame(MARGIN, 17 * mm, CONTENT_W, PAGE_H - 37 * mm, id="f", leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="cover", frames=frame, onPage=cover_fn),
                               PageTemplate(id="body", frames=frame, onPage=self._decorate)])

    def _decorate(self, canv, doc):
        canv.saveState()
        canv.setStrokeColor(C["line"])
        canv.setLineWidth(0.6)
        canv.line(MARGIN, PAGE_H - 13 * mm, PAGE_W - MARGIN, PAGE_H - 13 * mm)
        canv.setFont("Arial", 7.6)
        canv.setFillColor(C["muted"])
        canv.drawString(MARGIN, PAGE_H - 11.3 * mm, self.short)
        canv.drawRightString(PAGE_W - MARGIN, PAGE_H - 11.3 * mm, "PaymentLens · Enterprise AI Business Analyst")
        canv.line(MARGIN, 12 * mm, PAGE_W - MARGIN, 12 * mm)
        canv.drawString(MARGIN, 8.2 * mm, "Synthetic data · generated from the repository and recorded run outputs")
        canv.drawRightString(PAGE_W - MARGIN, 8.2 * mm, f"Page {doc.page}")
        canv.restoreState()

    def afterFlowable(self, f):
        lvl = getattr(f, "_toc_level", None)
        if lvl is not None:
            key = f._bookmark
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(f.getPlainText(), key, level=lvl, closed=lvl > 0)
            self.notify("TOCEntry", (lvl, f.getPlainText(), self.page, key))


class Book:
    def __init__(self, path: Path, title: str, subtitle: str, short: str, cover_lines: list[str], accent="#2a78d6"):
        self.path, self.title, self.subtitle, self.short = path, title, subtitle, short
        self.cover_lines, self.accent = cover_lines, colors.HexColor(accent)
        self.story: list = [Spacer(1, 1), NextPageTemplate("body"), PageBreak()]
        self.n1 = self.n2 = self.nfig = 0

    def _cover(self, canv, doc):
        canv.saveState()
        canv.setFillColor(C["navy"])
        canv.rect(0, PAGE_H - 108 * mm, PAGE_W, 108 * mm, stroke=0, fill=1)
        canv.setFillColor(self.accent)
        canv.rect(0, PAGE_H - 112 * mm, PAGE_W, 4 * mm, stroke=0, fill=1)
        canv.setFillColor(colors.white)
        canv.setFont("Arial", 10.5)
        canv.drawString(MARGIN, PAGE_H - 28 * mm, "PAYMENTLENS · ENTERPRISE AI BUSINESS ANALYST · CHALLENGE 2")
        canv.setFont("Arial-Bold", 25)
        y = PAGE_H - 47 * mm
        for line in textwrap.wrap(self.title, 34):
            canv.drawString(MARGIN, y, line)
            y -= 10.5 * mm
        canv.setFont("Arial", 12)
        y -= 1 * mm
        for line in textwrap.wrap(self.subtitle, 72):
            canv.drawString(MARGIN, y, line)
            y -= 6.3 * mm
        canv.setFillColor(C["ink"])
        y = PAGE_H - 128 * mm
        canv.setFont("Arial-Bold", 10.5)
        canv.drawString(MARGIN, y, "About this document")
        canv.setFont("Arial", 9.4)
        y -= 7 * mm
        for line in self.cover_lines:
            for w in textwrap.wrap(line, 104):
                canv.drawString(MARGIN, y, w)
                y -= 5 * mm
            y -= 1.6 * mm
        y -= 4 * mm
        canv.setFont("Arial-Bold", 10.5)
        canv.drawString(MARGIN, y, "Status labels used throughout")
        y -= 7 * mm
        for key, (label, col) in STATUS_TAG.items():
            if key == "untested":  # no longer used: the OpenAI path has been run live
                continue
            canv.setFillColor(colors.HexColor(col))
            canv.setFont("Arial-Bold", 8.4)
            canv.drawString(MARGIN, y, f"[{label}]")
            canv.setFillColor(C["ink"])
            canv.setFont("Arial", 8.4)
            canv.drawString(MARGIN + 60 * mm, y, STATUS_MEANING[key])
            y -= 5.6 * mm
        canv.setFillColor(C["muted"])
        canv.setFont("Arial", 8)
        canv.drawString(MARGIN, 14 * mm, f"Generated {date.today():%d %B %Y} · {self.path.name}")
        canv.restoreState()

    def toc(self):
        self.story.append(Paragraph("Contents", S["h1"]))
        self.story += [TableOfContents(levelStyles=[S["toc0"], S["toc1"]], dotsMinLevel=0), PageBreak()]

    # ------------------------------------------------------------------ text
    def h1(self, title: str):
        self.n1 += 1
        self.n2 = 0
        if self.n1 > 1:
            self.story.append(PageBreak())
        p = Paragraph(f"{self.n1}. {esc(title)}", S["h1"])
        p._toc_level, p._bookmark = 0, f"s{self.n1}"
        self.story += [p, _Rule()]

    def h2(self, title: str):
        self.n2 += 1
        p = Paragraph(f"{self.n1}.{self.n2} {esc(title)}", S["h2"])
        p._toc_level, p._bookmark = 1, f"s{self.n1}_{self.n2}"
        self.story += [CondPageBreak(34 * mm), p]

    def h3(self, title: str):
        self.story += [CondPageBreak(24 * mm), Paragraph(title, S["h3"])]

    def p(self, text: str, style="body"):
        self.story.append(Paragraph(text, S[style]))

    def bullets(self, items: list[str], numbered: bool = False):
        for i, it in enumerate(items, 1):
            self.story.append(Paragraph(it, S["bullet"], bulletText=f"{i}." if numbered else "•"))
        self.story.append(Spacer(1, 3))

    def space(self, h=4):
        self.story.append(Spacer(1, h))

    def pagebreak(self):
        self.story.append(PageBreak())

    # ------------------------------------------------------------------ blocks
    def code(self, text: str, title: str | None = None, width_chars: int = 112, chunk: int = 46):
        lines: list[str] = []
        for raw in text.rstrip("\n").splitlines():
            raw = raw.replace("\t", "    ")
            if len(raw) <= width_chars:
                lines.append(raw)
                continue
            indent = len(raw) - len(raw.lstrip())
            parts = textwrap.wrap(raw.strip(), width_chars - indent - 2, break_long_words=True, break_on_hyphens=False)
            lines.append(" " * indent + parts[0])
            lines += [" " * (indent + 2) + q for q in parts[1:]]
        blocks = [lines[i:i + chunk] for i in range(0, len(lines), chunk)] or [[""]]
        if title:
            self.story.append(CondPageBreak(30 * mm))
            self.story.append(Paragraph(f'<font name="Arial-Bold" size="7.8" color="#52514e">{esc(title)}</font>', S["small"]))
        for b in blocks:
            html = "<br/>".join(esc(x).replace(" ", "&nbsp;") or "&nbsp;" for x in b)
            t = Table([[Paragraph(html, S["code"])]], colWidths=[CONTENT_W])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C["code"]), ("BOX", (0, 0), (-1, -1), 0.5, C["line"]),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            self.story.append(t)
        self.story.append(Spacer(1, 6))

    def table(self, rows: list[list], widths: list[float] | None = None, header: bool = True, code_cols=(), font=None):
        widths = widths or [1 / len(rows[0])] * len(rows[0])
        cw = [w * CONTENT_W for w in widths]
        data = []
        for r_i, row in enumerate(rows):
            cells = []
            for c_i, cell in enumerate(row):
                st = S["cellhead"] if (header and r_i == 0) else (S["cellcode"] if c_i in code_cols else S["cell"])
                if font and not (header and r_i == 0):
                    st = ParagraphStyle("x", parent=st, fontSize=font, leading=font * 1.3)
                cells.append(Paragraph(str(cell), st))
            data.append(cells)
        t = Table(data, colWidths=cw, repeatRows=1 if header else 0)
        style = [("GRID", (0, 0), (-1, -1), 0.4, C["line"]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                 ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), C["head"]))
        for i in range(1 if header else 0, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), C["zebra"]))
        t.setStyle(TableStyle(style))
        self.story += [t, Spacer(1, 7)]

    def callout(self, text: str, kind: str = "note", title: str | None = None):
        palette = {"note": ("#e8f1fc", "#2a78d6", "Note"), "hinglish": ("#fff4e5", "#c25220", "Easy Hinglish"),
                   "say": ("#eaf6ea", "#0a7a0a", "Say this"), "warn": ("#fdecec", "#c53030", "Important"),
                   "honest": ("#f3f0fc", "#6250d6", "Honest status"), "tip": ("#f1f1ee", "#52514e", "Tip")}
        bg, bar, default = palette[kind]
        head = f'<font name="Arial-Bold" color="{bar}">{esc(title or default)}</font><br/>'
        t = Table([["", Paragraph(head + text, S["callout"])]], colWidths=[3, CONTENT_W - 3])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), colors.HexColor(bar)),
                               ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(bg)),
                               ("LEFTPADDING", (1, 0), (1, 0), 9), ("RIGHTPADDING", (1, 0), (1, 0), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                               ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0)]))
        self.story += [t, Spacer(1, 7)]

    def image(self, path: Path, width_frac: float = 1.0, caption: str | None = None):
        from reportlab.lib.utils import ImageReader
        iw, ih = ImageReader(str(path)).getSize()
        w = CONTENT_W * width_frac
        self.nfig += 1
        items = [Image(str(path), width=w, height=w * ih / iw)]
        if caption:
            items.append(Paragraph(f"Figure {self.nfig}. {caption}", S["caption"]))
        self.story.append(KeepTogether(items))

    def drawing(self, d: Drawing, caption: str | None = None):
        self.nfig += 1
        items = [d] + ([Paragraph(f"Figure {self.nfig}. {caption}", S["caption"])] if caption else [])
        self.story.append(KeepTogether(items))

    def build(self):
        _Doc(self.path, self.title, self.short, self._cover).multiBuild(self.story)


class _Rule(Table):
    def __init__(self):
        super().__init__([[""]], colWidths=[CONTENT_W], rowHeights=[2])
        self.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 1.2, C["blue"])]))


# ----------------------------------------------------------------------------- diagrams
def _box(d, x, y, w, h, lines, fill, size=7.6):
    d.add(Rect(x, y, w, h, rx=4, ry=4, fillColor=fill, strokeColor=C["muted"], strokeWidth=0.6))
    n = len(lines)
    top = y + h / 2 + (n - 1) * (size + 1.6) / 2 - size / 3
    for i, ln in enumerate(lines):
        d.add(String(x + w / 2, top - i * (size + 1.6), ln, fontName="Arial-Bold" if i == 0 else "Arial",
                     fontSize=size if i == 0 else size - 0.6, fillColor=C["ink"], textAnchor="middle"))


def _arrow(d, x1, y1, x2, y2, color=None, label=None):
    color = color or C["muted"]
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=0.9))
    ang = math.atan2(y2 - y1, x2 - x1)
    a, s = 0.45, 5
    d.add(Polygon([x2, y2, x2 - s * math.cos(ang - a), y2 - s * math.sin(ang - a),
                   x2 - s * math.cos(ang + a), y2 - s * math.sin(ang + a)], fillColor=color, strokeColor=color))
    if label:
        d.add(String((x1 + x2) / 2 + 3, (y1 + y2) / 2 + 3, label, fontName="Arial", fontSize=6.4, fillColor=C["muted"]))


def pipeline_diagram(steps: list[tuple[str, str, str]]) -> Drawing:
    """Draws the pipeline as boxes in two columns. Each step is (title, subtitle, colour type)."""
    W = CONTENT_W
    half = (len(steps) + 1) // 2
    bw, bh, gap, top = 212, 32, 13, 34
    H = half * (bh + gap) + top
    d = Drawing(W, H)
    xs = [10, W - 10 - bw]
    pos = []
    for i, (t, sub, kind) in enumerate(steps):
        col = 0 if i < half else 1
        row = i if i < half else (len(steps) - 1 - i) + (half * 2 - len(steps))
        y = H - top - (row + 1) * (bh + gap) + gap
        pos.append((xs[col], y))
        _box(d, xs[col], y, bw, bh, [t, sub], C[kind])
    for i in range(len(steps) - 1):
        (x1, y1), (x2, y2) = pos[i], pos[i + 1]
        if x1 == x2:
            if y2 < y1:
                _arrow(d, x1 + bw / 2, y1, x2 + bw / 2, y2 + bh)
            else:
                _arrow(d, x1 + bw / 2, y1 + bh, x2 + bw / 2, y2)
        else:
            _arrow(d, x1 + bw, y1 + bh / 2, x2, y2 + bh / 2)
    lx = 10
    for kind, label in (("ai", "AI step (optional, with fallback)"), ("det", "Deterministic Python / SQL"),
                        ("sec", "Security / governance"), ("data", "Data / storage / UI")):
        d.add(Rect(lx, H - 16, 11, 8, fillColor=C[kind], strokeColor=C["muted"], strokeWidth=0.5))
        d.add(String(lx + 15, H - 14.5, label, fontName="Arial", fontSize=7, fillColor=C["ink"]))
        lx += 122
    return d


def sequence_diagram(parts: list[str], msgs: list[tuple[int, int, str]], row=16.5) -> Drawing:
    W = CONTENT_W
    n = len(parts)
    colw = W / n
    H = 36 + len(msgs) * row + 10
    d = Drawing(W, H)
    xs = [colw * i + colw / 2 for i in range(n)]
    for i, p in enumerate(parts):
        bw = min(colw - 5, 88)
        lines = p.split("\n")
        _box(d, xs[i] - bw / 2, H - 28, bw, 24, lines, C["det"], size=6.6)
        d.add(Line(xs[i], H - 28, xs[i], 4, strokeColor=C["line"], strokeWidth=0.8, strokeDashArray=[2, 2]))
    y = H - 42
    for k, (a, b, label) in enumerate(msgs, 1):
        txt = f"{k}. {label}"
        if a == b:
            d.add(Line(xs[a], y, xs[a] + 12, y, strokeColor=C["muted"], strokeWidth=0.8))
            d.add(Line(xs[a] + 12, y, xs[a] + 12, y - 6, strokeColor=C["muted"], strokeWidth=0.8))
            _arrow(d, xs[a] + 12, y - 6, xs[a] + 1, y - 6)
            d.add(String(xs[a] + 15, y - 4, txt, fontName="Arial", fontSize=6.3, fillColor=C["ink"]))
        else:
            _arrow(d, xs[a], y, xs[b], y, color=C["blue"] if b > a else C["green"])
            d.add(String(min(xs[a], xs[b]) + 3, y + 2.5, txt, fontName="Arial", fontSize=6.3, fillColor=C["ink"]))
        y -= row
    return d


def er_diagram(tables: dict[str, list[str]]) -> Drawing:
    W, H = CONTENT_W, 300
    d = Drawing(W, H)
    layout = {"transactions (VIEW)": (178, 236), "transactions_raw": (178, 22), "merchants": (4, 40),
              "banks": (352, 196), "settlements": (352, 22)}
    boxes = {}
    for name, cols in tables.items():
        x, y = layout[name]
        w = 136
        h = 20 + 9 * len(cols)
        fill = C["ok"] if "VIEW" in name else C["det"]
        d.add(Rect(x, y, w, h, fillColor=colors.white, strokeColor=C["muted"], strokeWidth=0.7))
        d.add(Rect(x, y + h - 14, w, 14, fillColor=fill, strokeColor=C["muted"], strokeWidth=0.7))
        d.add(String(x + 4, y + h - 10, name, fontName="Arial-Bold", fontSize=7.4, fillColor=C["ink"]))
        for i, c in enumerate(cols):
            d.add(String(x + 4, y + h - 24 - i * 9, c, fontName="Consolas", fontSize=6.3, fillColor=C["ink"]))
        boxes[name] = (x, y, w, h)
    tr, tv, me, ba, se = (boxes[k] for k in ("transactions_raw", "transactions (VIEW)", "merchants", "banks", "settlements"))
    _arrow(d, tr[0] + tr[2] / 2, tr[1] + tr[3], tv[0] + tv[2] / 2, tv[1], label="dedup + validity rules")
    _arrow(d, tr[0], tr[1] + tr[3] * 0.7, me[0] + me[2], me[1] + me[3] * 0.7)
    _arrow(d, tr[0] + tr[2], tr[1] + tr[3] * 0.85, ba[0], ba[1] + ba[3] / 2, label="bank_id")
    _arrow(d, se[0], se[1] + se[3] / 2, tr[0] + tr[2], tr[1] + tr[3] * 0.35)
    return d
