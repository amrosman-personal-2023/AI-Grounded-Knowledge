"""Render one chat message (assistant answer + its citations) to a styled PDF."""
import io
import re
import html

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    HRFlowable,
)

BLUE = colors.HexColor("#1B4B8F")
GREY = colors.HexColor("#555555")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Q", parent=ss["Normal"], fontSize=11, leading=15,
                          textColor=GREY, spaceAfter=6))
    ss.add(ParagraphStyle("Ans", parent=ss["Normal"], fontSize=11, leading=16,
                          spaceAfter=6))
    ss.add(ParagraphStyle("H", parent=ss["Heading1"], fontSize=15, leading=19,
                          textColor=BLUE, spaceAfter=4))
    ss.add(ParagraphStyle("Meta", parent=ss["Normal"], fontSize=8, textColor=GREY))
    ss.add(ParagraphStyle("CiteHdr", parent=ss["Heading2"], fontSize=11,
                          textColor=BLUE, spaceBefore=8, spaceAfter=4))
    ss.add(ParagraphStyle("Cite", parent=ss["Normal"], fontSize=8.5, leading=12,
                          textColor=GREY, spaceAfter=3, leftIndent=10))
    return ss


def _md_inline(text):
    """Minimal markdown → reportlab inline markup, on escaped text."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', t)
    t = re.sub(r"\[(\d+)\]", r'<b><font color="#1B4B8F">[\1]</font></b>', t)
    return t


def _blocks(answer, styles):
    """Split answer into paragraphs / bullets as flowables."""
    out = []
    for raw in answer.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            out.append(Spacer(1, 4))
            continue
        m = re.match(r"^\s*(?:[-*•]|\d+\.)\s+(.*)", line)
        if m:
            out.append(Paragraph("• " + _md_inline(m.group(1)), styles["Ans"]))
        elif re.match(r"^#{1,4}\s+", line):
            out.append(Paragraph(_md_inline(re.sub(r"^#{1,4}\s+", "", line)), styles["H"]))
        else:
            out.append(Paragraph(_md_inline(line), styles["Ans"]))
    return out


def render_message(question, answer, citations, prepared_by="GND Assistant",
                   conversation_title=None):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.8 * inch, bottomMargin=0.8 * inch,
        title=conversation_title or "GND Export",
    )
    s = _styles()
    flow = [Paragraph("GND — Grounded Knowledge Assistant", s["H"])]
    if conversation_title:
        flow.append(Paragraph(html.escape(conversation_title), s["Meta"]))
    flow.append(HRFlowable(width="100%", thickness=1, color=BLUE, spaceAfter=8))

    if question:
        flow.append(Paragraph("<b>Question</b>", s["CiteHdr"]))
        flow.append(Paragraph(_md_inline(question), s["Q"]))

    flow.append(Paragraph("<b>Answer</b>", s["CiteHdr"]))
    flow.extend(_blocks(answer, s))

    if citations:
        flow.append(Spacer(1, 6))
        flow.append(HRFlowable(width="100%", thickness=0.5, color=GREY, spaceAfter=4))
        flow.append(Paragraph("Sources", s["CiteHdr"]))
        for c in citations:
            aud = f' <font color="#B00">[{html.escape(c["audience"])}]</font>' if c.get("audience") == "Internal" else ""
            label = html.escape(c.get("label") or "")
            url = c.get("url")
            if url:
                label = f'<a href="{html.escape(url, quote=True)}" color="#1B4B8F"><u>{label}</u></a>'
            flow.append(Paragraph(f'[{c["n"]}] {label}{aud}', s["Cite"]))

    flow.append(Spacer(1, 12))
    flow.append(HRFlowable(width="100%", thickness=0.5, color=GREY, spaceAfter=4))
    flow.append(Paragraph(f"Prepared by {html.escape(prepared_by)} · GND "
                          f"· grounded in the local knowledge corpus", s["Meta"]))

    doc.build(flow)
    return buf.getvalue()
