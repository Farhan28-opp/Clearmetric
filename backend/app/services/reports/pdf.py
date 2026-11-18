"""PDF rendering of report snapshots with ReportLab (vector charts, print typography)."""
import io
from datetime import datetime, timezone

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

from app.services.analytics.format import CURRENCY_SYMBOLS, fmt_value

INK = colors.HexColor("#17201b")
MUTED = colors.HexColor("#5b665f")
ACCENT = colors.HexColor("#1f6b52")
LINE = colors.HexColor("#d9ddd5")
PAPER = colors.HexColor("#f6f4ee")
SERIES = ["#1f6b52", "#c0703a", "#3f6fa8", "#8a5aa0", "#a8943f", "#4f8f8a", "#b0506a", "#6b6b6b"]

S = {
    "title": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=INK, spaceAfter=4),
    "subtitle": ParagraphStyle("st", fontName="Helvetica", fontSize=11, leading=15, textColor=MUTED, spaceAfter=10),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13.5, leading=18, textColor=INK, spaceBefore=12, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=ACCENT, spaceBefore=6, spaceAfter=3),
    "body": ParagraphStyle("b", fontName="Helvetica", fontSize=10, leading=14.5, textColor=INK, alignment=TA_LEFT, spaceAfter=5),
    "small": ParagraphStyle("s", fontName="Helvetica", fontSize=8, leading=11, textColor=MUTED),
    "bullet": ParagraphStyle("bl", fontName="Helvetica", fontSize=10, leading=14, textColor=INK, leftIndent=10, bulletIndent=0, spaceAfter=2),
    "label": ParagraphStyle("l", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED),
    "kpi": ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=INK),
    "cell": ParagraphStyle("c", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK),
}


def esc(t) -> str:
    # Core PDF fonts have no rupee glyph; spell it out so amounts stay readable
    return str(t if t is not None else "").replace("₹", "Rs ").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Fmt:
    def __init__(self, currency):
        self.c = currency
        self.sym = CURRENCY_SYMBOLS.get(currency, currency + " ")

    def __call__(self, v, unit="number", decimals=2):
        if unit == "pct":
            return "—" if v is None else f"{v:.1f}%"
        if unit == "percent_points":
            return "—" if v is None else f"{v * 100:+.1f} pp"
        s = fmt_value(v, unit, self.c, decimals)
        return s.replace("₹", "Rs ") if "₹" in s else s  # core PDF fonts lack the rupee glyph


def _chart(snap: dict, f: Fmt) -> Drawing | None:
    chart = snap.get("chart") or {}
    rows = snap.get("rows") or []
    cols = snap.get("columns") or []
    ctype = chart.get("type")
    if not rows or ctype in (None, "kpi", "table"):
        return None
    xkey = chart.get("x")
    ykeys = chart.get("y") or []
    if not xkey or not ykeys:
        return None
    ycol = next((c for c in cols if c["key"] == ykeys[0]), {"label": "", "unit": "number"})
    W, H = 170 * mm, 70 * mm
    d = Drawing(W, H)
    if ctype == "line":
        series_key = chart.get("series")
        xs = []
        for r in rows:
            if r.get(xkey) not in xs:
                xs.append(r.get(xkey))
        groups = {}
        for r in rows:
            g = r.get(series_key) if series_key else ycol["label"]
            groups.setdefault(g, {})[r.get(xkey)] = r.get(ykeys[0]) or 0
        lp = LinePlot()
        lp.x, lp.y, lp.width, lp.height = 45, 30, W - 140 if series_key else W - 60, H - 45
        lp.data = [[(i, vals.get(x, 0)) for i, x in enumerate(xs)] for vals in list(groups.values())[:8]]
        for i in range(len(lp.data)):
            lp.lines[i].strokeColor = colors.HexColor(SERIES[i % len(SERIES)])
            lp.lines[i].strokeWidth = 1.6
        lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0, max(len(xs) - 1, 1)
        step = max(1, len(xs) // 8)
        lp.xValueAxis.valueSteps = list(range(0, len(xs), step))
        lp.xValueAxis.labelTextFormat = lambda v: str(xs[int(v)])[:8] if 0 <= int(v) < len(xs) else ""
        lp.xValueAxis.labels.fontSize = 6.5
        lp.yValueAxis.labels.fontSize = 7
        lp.xValueAxis.labels.fontName = lp.yValueAxis.labels.fontName = "Helvetica"
        lp.xValueAxis.labels.fillColor = lp.yValueAxis.labels.fillColor = MUTED
        lp.yValueAxis.labelTextFormat = lambda v: f(v, ycol.get("unit", "number"), 0)
        lp.yValueAxis.gridStrokeColor, lp.yValueAxis.visibleGrid = LINE, True
        d.add(lp)
        if series_key:
            for i, g in enumerate(list(groups)[:8]):
                d.add(String(W - 88, H - 18 - i * 10, f"— {str(g)[:16]}", fontSize=7, fontName="Helvetica-Bold", fillColor=colors.HexColor(SERIES[i % len(SERIES)])))
        return d
    data_rows = [r for r in rows if r.get(xkey) is not None][:14]
    vals = [float(r.get(ykeys[0]) or 0) for r in data_rows]
    labels = [str(r.get(xkey))[:18] for r in data_rows]
    horizontal = ctype in ("hbar", "donut") or len(max(labels, key=len, default="")) > 10
    bc = HorizontalBarChart() if horizontal else VerticalBarChart()
    if horizontal:
        H = max(50 * mm, (len(vals) * 7 + 12) * mm / 2.2)
        d = Drawing(W, H)
        bc.x, bc.y, bc.width, bc.height = 95, 15, W - 130, H - 25
        bc.data = [list(reversed(vals))]
        bc.categoryAxis.categoryNames = list(reversed(labels))
    else:
        bc.x, bc.y, bc.width, bc.height = 45, 30, W - 60, H - 45
        bc.data = [vals]
        bc.categoryAxis.categoryNames = labels
        bc.categoryAxis.labels.angle = 30 if len(labels) > 6 else 0
        bc.categoryAxis.labels.boxAnchor = "ne" if len(labels) > 6 else "n"
    bc.bars[0].fillColor = ACCENT
    bc.bars[0].strokeColor = None
    if ctype == "waterfall":
        for i, v in enumerate(bc.data[0]):
            bc.bars[(0, i)].fillColor = colors.HexColor("#b4533c") if v < 0 else ACCENT
    bc.valueAxis.labels.fontSize = 7
    bc.categoryAxis.labels.fontSize = 7
    bc.valueAxis.labels.fontName = bc.categoryAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labels.fillColor = bc.categoryAxis.labels.fillColor = MUTED
    bc.valueAxis.labelTextFormat = lambda v: f(v, ycol.get("unit", "number"), 0) if ycol.get("role") != "percent" else f"{v:.0f}%"
    bc.valueAxis.visibleGrid, bc.valueAxis.gridStrokeColor = True, LINE
    lo = min(vals + [0])
    bc.valueAxis.valueMin = lo * 1.1 if lo < 0 else 0
    d.add(bc)
    return d


def _table(snap: dict, f: Fmt, max_rows=15) -> Table | None:
    cols = (snap.get("columns") or [])[:6]
    rows = (snap.get("rows") or [])[:max_rows]
    if not cols or not rows:
        return None

    def cell(r, c):
        v = r.get(c["key"])
        if v is None:
            return "—"
        if c.get("role") == "percent":
            return f"{v:.1f}%"
        if c.get("role") == "measure" and isinstance(v, (int, float)):
            return f(v, c.get("unit", "number"), c.get("decimals", 2))
        if isinstance(v, float):
            return f"{v:,.2f}"
        return str(v)[:40]
    data = [[Paragraph(f"<b>{esc(c['label'])}</b>", S["cell"]) for c in cols]] + \
           [[Paragraph(esc(cell(r, c)), S["cell"]) for c in cols] for r in rows]
    t = Table(data, repeatRows=1, hAlign="LEFT", colWidths=[170 * mm / len(cols)] * len(cols))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PAPER), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _kpi_grid(items: list[tuple[str, str, str]]) -> Table:
    cells = [[Paragraph(esc(l.upper()), S["label"]), Paragraph(esc(v), S["kpi"]), Paragraph(esc(sub), S["small"])] for l, v, sub in items]
    rows = [cells[i:i + 3] for i in range(0, len(cells), 3)]
    rows = [r + [""] * (3 - len(r)) for r in rows]
    t = Table([[c if c else "" for c in r] for r in rows], colWidths=[57 * mm] * 3)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
    return t


def _provenance_line(snap: dict) -> str:
    p = snap.get("provenance") or {}
    ds = p.get("dataset") or {}
    if not ds:
        return ""
    return (f"Source: {ds.get('name')} v{ds.get('version_number')} · {p.get('records_in_scope', 0):,} records · "
            f"{p.get('date_range', '')} · computed {str(p.get('executed_at', ''))[:16].replace('T', ' ')} UTC")


def render(report: dict, workspace: dict) -> bytes:
    f = Fmt(workspace.get("currency", "USD"))
    buf = io.BytesIO()
    generated = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    def frame(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(ACCENT)
        canvas.rect(20 * mm, A4[1] - 14 * mm, 6 * mm, 1.2 * mm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(INK)
        canvas.drawString(28 * mm, A4[1] - 14 * mm, "CLEARMETRIC")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 14 * mm, esc(report["title"])[:80])
        canvas.drawString(20 * mm, 12 * mm, f"{workspace.get('name', '')} · Generated {generated}")
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=22 * mm, bottomMargin=20 * mm,
                            title=report["title"], author="ClearMetric")
    story = [Paragraph(esc(report["title"]), S["title"])]
    meta = [report.get("subtitle") or "", f"Dataset: {report.get('dataset_name') or '—'}",
            f"Reporting period: {report.get('period_label') or 'As stated per section'}", f"Status: {report.get('status', 'draft').title()}"]
    story.append(Paragraph(" · ".join(esc(m) for m in meta if m), S["subtitle"]))
    if report.get("is_demo"):
        story.append(Paragraph("<b>Synthetic demonstration data.</b> Figures in this report are generated from a synthetic dataset, not real business records.", S["small"]))
    story.append(Spacer(1, 6))
    methods = []
    for sec in report["sections"]:
        snap = sec.get("snapshot") or {}
        block = []
        if sec.get("title"):
            block.append(Paragraph(esc(sec["title"]), S["h2"]))
        kind = sec["kind"]
        if kind in ("text", "recommendations"):
            for para in (sec.get("body") or "").split("\n"):
                if para.strip():
                    block.append(Paragraph(("• " if para.strip().startswith(("-", "•")) else "") + esc(para.strip().lstrip("-• ")),
                                           S["bullet"] if para.strip().startswith(("-", "•")) else S["body"]))
        elif kind == "summary":
            sm = snap
            ctx = sm.get("business_context", {})
            rp = sm.get("reporting_period", {})
            block.append(Paragraph(esc(f"{ctx.get('workspace')} · {ctx.get('dataset')} (v{ctx.get('dataset_version')}, {ctx.get('rows', 0):,} rows) · "
                                       f"{rp.get('current')} compared with {rp.get('baseline')}"), S["small"]))
            block.append(Spacer(1, 4))
            if sm.get("kpis"):
                items = []
                for k in sm["kpis"]:
                    items.append((k["metric"], f(k["current"], k["unit"]),
                                  (f"{(k['change_pct'] or 0):+.1f}% vs {f(k['baseline'], k['unit'])}" if k["change_pct"] is not None else "No baseline")))
                block.append(_kpi_grid(items))
            for title, key in (("Main performance changes", "main_changes"), ("Product and regional contributors", "contributors"),
                               ("Anomaly observations", "anomalies"), ("Important limitations", "limitations"),
                               ("Suggested next investigations", "next_investigations")):
                if sm.get(key):
                    block.append(Paragraph(title, S["h3"]))
                    block += [Paragraph(esc(x), S["bullet"], bulletText="•") for x in sm[key]]
                if key == "contributors" and sm.get("findings"):
                    block.append(Paragraph("Significant findings", S["h3"]))
                    block += [Paragraph(f"<b>{esc(x['title'])}</b> — {esc(x['finding'])}", S["bullet"], bulletText="•") for x in sm["findings"]]
            if sm.get("interpretation", {}).get("text"):
                block.append(Paragraph("Interpretation", S["h3"]))
                block.append(Paragraph(esc(sm["interpretation"]["text"]), S["body"]))
                block.append(Paragraph(esc(sm["interpretation"]["source"]) + ". Computed observations above are exact calculations.", S["small"]))
            methods.append(("Executive summary", "Each KPI is a verified metric computed for the reporting period and the preceding period of equal length: "
                            + "; ".join(f"{m['metric']} v{m['version']} = {m['formula']}" for m in sm.get("provenance", {}).get("metric_versions", []))))
        elif kind == "kpis":
            items = [(k["label"], f(k.get("value"), k.get("unit", "number"), k.get("decimals", 2)) if k.get("value") is not None else k.get("text", "—"), "")
                     for k in snap.get("kpis", [])]
            if items:
                block.append(_kpi_grid(items))
        elif kind == "insight":
            block.append(Paragraph(esc(snap.get("finding", "")), S["body"]))
            block.append(Paragraph(f"<b>Method:</b> {esc(snap.get('method', ''))}", S["small"]))
            if snap.get("limitations"):
                block.append(Paragraph(f"<b>Limitations:</b> {esc(snap['limitations'])}", S["small"]))
        elif kind in ("chart", "table"):
            if sec.get("body"):
                block.append(Paragraph(esc(sec["body"]), S["body"]))
            if snap.get("narrative"):
                block.append(Paragraph(esc(snap["narrative"]), S["body"]))
            if snap.get("kpis") and kind == "chart":
                items = [(k["label"], f(k.get("value"), k.get("unit", "number"), k.get("decimals", 2)) if k.get("value") is not None else k.get("text", "—"), "")
                         for k in snap["kpis"][:6]]
                block.append(_kpi_grid(items))
                block.append(Spacer(1, 4))
            if kind == "chart":
                ch = _chart(snap, f)
                if ch:
                    block.append(ch)
            t = _table(snap, f, 15 if kind == "table" else 8)
            if t:
                block.append(Spacer(1, 4))
                block.append(t)
            for n in snap.get("notes", [])[:3]:
                block.append(Paragraph(esc(n), S["small"]))
            if _provenance_line(snap):
                block.append(Paragraph(esc(_provenance_line(snap)), S["small"]))
            if snap.get("provenance", {}).get("methodology"):
                methods.append((sec.get("title") or "Analysis", snap["provenance"]["methodology"]))
        block.append(Spacer(1, 6))
        story.append(KeepTogether(block) if kind not in ("summary",) else block[0])
        if kind == "summary":
            story += block[1:]
    story.append(PageBreak())
    story.append(Paragraph("Methodology and data sources", S["h2"]))
    story.append(Paragraph(esc(f"Data source: {report.get('dataset_name')} (dataset version {report.get('dataset_version') or '—'}). "
                               "All figures were computed by ClearMetric's deterministic analytical engine (DuckDB) from validated analysis plans. "
                               "Sections store a snapshot of their results, so this report does not change when metric definitions change later."), S["body"]))
    for title, m in methods:
        story.append(Paragraph(f"<b>{esc(title)}.</b> {esc(m)}", S["body"]))
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()
